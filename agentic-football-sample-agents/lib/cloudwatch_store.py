"""Persist CloudWatch DECISION rows locally (JSONL under cloudwatch_logs/)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STORE_DIR = REPO / "cloudwatch_logs"


def _safe_prefix(prefix: str) -> str:
    p = (prefix or "all").strip().replace("/", "_")
    return p or "all"


def _store_path(prefix: str, day: str) -> Path:
    return STORE_DIR / f"{_safe_prefix(prefix)}{day}.jsonl"


def _parse_log_ts(ts: str | None) -> float | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            raw = ts[:26] if "." in ts[:26] else ts[:19]
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    return None


def _day_from_row(row: dict) -> str:
    ts = row.get("log_ts")
    if ts and len(ts) >= 10:
        return ts[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def row_key(row: dict) -> tuple:
    return (
        row.get("log_ts") or "",
        row.get("_log") or "",
        row.get("pos") or "",
        row.get("tick") or "",
        row.get("t") or "",
    )


def _sort_key(row: dict) -> tuple:
    ts = _parse_log_ts(row.get("log_ts")) or 0.0
    return (ts, row.get("t") or 0, row.get("tick") or 0)


def _existing_keys(path: Path) -> set[tuple]:
    if not path.exists():
        return set()
    keys: set[tuple] = set()
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    keys.add(row_key(json.loads(line)))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return keys


def append_decisions(prefix: str, rows: list[dict]) -> int:
    """Append new DECISION rows to daily JSONL files. Returns count added."""
    if not rows:
        return 0
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    by_day: dict[str, list[dict]] = {}
    for row in rows:
        by_day.setdefault(_day_from_row(row), []).append(row)

    added = 0
    for day, batch in by_day.items():
        path = _store_path(prefix, day)
        seen = _existing_keys(path)
        new_rows = [r for r in batch if row_key(r) not in seen]
        if not new_rows:
            continue
        with path.open("a", encoding="utf-8") as fh:
            for row in new_rows:
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                seen.add(row_key(row))
        added += len(new_rows)
    return added


def _glob_paths(prefix: str) -> list[Path]:
    pat = f"{_safe_prefix(prefix)}*.jsonl"
    return sorted(STORE_DIR.glob(pat))


def load_decisions(prefix: str, minutes: int | None = None) -> list[dict]:
    """Load stored rows for prefix, optionally limited to the last N minutes."""
    if not STORE_DIR.exists():
        return []
    cutoff = None
    if minutes is not None:
        cutoff = time.time() - minutes * 60
    # Read recent daily files only (today + yesterday covers timezone edge cases)
    days = {
        datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d"),
        (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d"),
    }
    if minutes and minutes > 2880:
        paths = _glob_paths(prefix)
    else:
        paths = [_store_path(prefix, d) for d in sorted(days)]
        paths = [p for p in paths if p.exists()]

    by_key: dict[tuple, dict] = {}
    for path in paths:
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if cutoff is not None:
                        ts = _parse_log_ts(row.get("log_ts"))
                        if ts is not None and ts < cutoff:
                            continue
                    by_key[row_key(row)] = row
        except OSError:
            continue
    return sorted(by_key.values(), key=_sort_key)


def merge_decisions(local: list[dict], cloud: list[dict]) -> list[dict]:
    """Union local + cloud rows; cloud wins on duplicate keys."""
    by_key = {row_key(r): r for r in local}
    for r in cloud:
        by_key[row_key(r)] = r
    return sorted(by_key.values(), key=_sort_key)


def store_stats(prefix: str) -> dict:
    paths = _glob_paths(prefix)
    total = 0
    oldest = newest = None
    for path in paths:
        try:
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        total += 1
                        try:
                            row = json.loads(line)
                            ts = row.get("log_ts")
                            if ts:
                                if oldest is None or ts < oldest:
                                    oldest = ts
                                if newest is None or ts > newest:
                                    newest = ts
                        except json.JSONDecodeError:
                            pass
        except OSError:
            continue
    return {
        "dir": str(STORE_DIR),
        "prefix": _safe_prefix(prefix),
        "files": len(paths),
        "rows": total,
        "oldest": oldest,
        "newest": newest,
    }
