"""Append-only partitioned storage.

Each table is stored as one gzipped CSV per **data date** under
``data/history/<table>/<date>.csv.gz``. A run rewrites only the partitions for
the dates it fetched, and only when their content actually changed, so git
stores each day's rows once instead of a fresh copy of a whole table on every
commit.

That is what makes daily collection affordable. Rewriting the consolidated CSVs
each day would add a new compressed blob of every changed file to git history
every commit — about 16 MB a day, 6 GB a year. Partitioned, the same collection
costs under a megabyte a day.

It is also what extends the record. OpenRouter serves only the last 8 days of
cache-hit, throughput, latency and error-rate data; partitions accumulated daily
keep those days after the API has dropped them, which is the whole point of
running this on a schedule.

Static tables (catalogues, current summaries) have no date of their own, so they
are partitioned by run date and written only when they differ from the most
recent partition — a catalogue that has not changed adds nothing.
"""

from __future__ import annotations

import csv
import gzip
import io
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .storage import SCHEMAS, TABLE_KEYS


def _render(rows: List[Dict[str, Any]], fields: List[str]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _read(path: str) -> List[Dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_if_changed(path: str, payload: bytes) -> bool:
    """Write only when the content differs, so unchanged days stay untouched."""
    if os.path.exists(path):
        try:
            with gzip.open(path, "rb") as f:
                if f.read() == payload:
                    return False
        except OSError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # mtime=0 keeps the gzip header byte-identical for identical content.
    with open(path, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as f:
            f.write(payload)
    return True


def partition_dir(root: str, stem: str) -> str:
    return os.path.join(root, stem)


def write(root: str, stem: str, rows: List[Dict[str, Any]], run_date: str) -> Tuple[int, int]:
    """Write one table's rows as date partitions. Returns (written, unchanged)."""
    fields = SCHEMAS[stem]
    time_column = TABLE_KEYS[stem][0]

    groups: Dict[str, List[Dict[str, Any]]] = {}
    if time_column:
        for row in rows:
            stamp = str(row.get(time_column) or "")[:10]
            if stamp:
                groups.setdefault(stamp, []).append(row)
    elif rows:
        groups[run_date] = list(rows)

    written = unchanged = 0
    for date, group in groups.items():
        path = os.path.join(partition_dir(root, stem), f"{date}.csv.gz")
        payload = _render(group, fields)
        if time_column is None:
            # Static table: skip when identical to the newest partition already held.
            latest = _latest_partition(root, stem)
            if latest and os.path.basename(latest) != f"{date}.csv.gz":
                try:
                    with gzip.open(latest, "rb") as f:
                        if f.read() == payload:
                            unchanged += 1
                            continue
                except OSError:
                    pass
        if _write_if_changed(path, payload):
            written += 1
        else:
            unchanged += 1
    return written, unchanged


def _latest_partition(root: str, stem: str) -> Optional[str]:
    directory = partition_dir(root, stem)
    if not os.path.isdir(directory):
        return None
    names = sorted(n for n in os.listdir(directory) if n.endswith(".csv.gz"))
    return os.path.join(directory, names[-1]) if names else None


def tables(root: str) -> List[str]:
    if not os.path.isdir(root):
        return []
    return sorted(n for n in os.listdir(root) if os.path.isdir(os.path.join(root, n)))


def load(root: str, stem: str) -> List[Dict[str, Any]]:
    """Read every partition, newest wins on a key collision.

    The most recent day is partial while it is being written and settles later,
    so a newer partition's version of the same key supersedes an older one.
    """
    directory = partition_dir(root, stem)
    if not os.path.isdir(directory):
        return []
    keys = TABLE_KEYS[stem][1]
    merged: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    for name in sorted(n for n in os.listdir(directory) if n.endswith(".csv.gz")):
        for row in _read(os.path.join(directory, name)):
            merged[tuple(str(row.get(k, "")) for k in keys)] = row
    return list(merged.values())


def summarise(root: str) -> Iterable[Tuple[str, int, int, str]]:
    """(table, partitions, rows, span) for each table held in history."""
    for stem in tables(root):
        directory = partition_dir(root, stem)
        names = sorted(n for n in os.listdir(directory) if n.endswith(".csv.gz"))
        rows = sum(max(0, sum(1 for _ in gzip.open(os.path.join(directory, n), "rt")) - 1)
                   for n in names)
        span = f"{names[0][:-7]} .. {names[-1][:-7]}" if names else ""
        yield stem, len(names), rows, span
