"""Day-scoped aggregation for scheduled signal buckets.

Each basket scan still writes its own timestamped watchlist, but scheduled
profiles also copy that result into outputs/daily/YYYY-MM-DD/<bucket>.json and
rebuild a combined board from *today's* bucket files only. Tomorrow naturally
starts clean because it uses a different folder.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scanner.config import get_config


def ingest(path: str | Path, bucket: str, *, max_per_bucket: int | None = None) -> Path:
    """Add one bucket result to today's board and rewrite outputs/latest.json.

    Returns the combined-board path. The bucket file is overwritten, not appended,
    so re-running a basket updates that basket without duplicating stale picks.
    """
    src = Path(path)
    watchlist = json.loads(src.read_text())
    day = _scan_day(watchlist)
    outputs = get_config().project_root / "outputs"
    day_dir = outputs / "daily" / day
    day_dir.mkdir(parents=True, exist_ok=True)

    slug = _slug(bucket or watchlist.get("directive") or src.stem)
    bucket_path = day_dir / f"{slug}.json"
    watchlist["bucket"] = bucket
    watchlist["bucket_slug"] = slug
    watchlist["source_output"] = src.name
    bucket_path.write_text(json.dumps(watchlist, indent=2, default=str))

    combined = combine(day_dir, max_per_bucket=max_per_bucket)
    combined_path = day_dir / "combined.json"
    combined_path.write_text(json.dumps(combined, indent=2, default=str))
    (outputs / "latest.json").write_text(json.dumps(combined, indent=2, default=str))
    return combined_path


def combine(day_dir: str | Path, *, max_per_bucket: int | None = None) -> dict:
    day_dir = Path(day_dir)
    boards = []
    for f in sorted(day_dir.glob("*.json")):
        if f.name == "combined.json":
            continue
        try:
            boards.append(json.loads(f.read_text()))
        except Exception:  # noqa: BLE001
            continue

    items = []
    seen: dict[str, dict] = {}
    bucket_counts: dict[str, int] = {}
    for board in boards:
        bucket = board.get("bucket") or board.get("directive") or "bucket"
        slug = board.get("bucket_slug") or _slug(bucket)
        take = board.get("watchlist") or []
        if max_per_bucket:
            take = take[:max_per_bucket]
        bucket_counts[slug] = len(take)
        for item in take:
            it = dict(item)
            it["source_bucket"] = bucket
            it["source_bucket_slug"] = slug
            key = str(it.get("symbol") or "").upper()
            if not key:
                items.append(it)
                continue
            prev = seen.get(key)
            if prev is None or _balanced_score(it) > _balanced_score(prev):
                seen[key] = it

    if seen:
        items = list(seen.values()) + [it for it in items if not it.get("symbol")]

    items.sort(key=_sort_key)
    _rerank_profiles(items)
    for i, item in enumerate(items, start=1):
        item["rank"] = i

    first = min((b.get("generated_at") for b in boards if b.get("generated_at")), default=None)
    last = max((b.get("generated_at") for b in boards if b.get("generated_at")), default=None)
    day = day_dir.name
    return {
        "generated_at": last or datetime.now(timezone.utc).isoformat(),
        "board_date": day,
        "combined_board": True,
        "directive": f"Daily combined board · {day}",
        "total_scanned": sum(int(b.get("total_scanned") or 0) for b in boards),
        "total_screened": sum(int(b.get("total_screened") or 0) for b in boards),
        "provider": (boards[-1].get("provider") if boards else get_config().llm_provider),
        "bucket_count": len(boards),
        "bucket_counts": bucket_counts,
        "bucket_files": [b.get("source_output") for b in boards if b.get("source_output")],
        "bucket_window": {"first": first, "last": last},
        "macro": _latest_nonempty(boards, "macro", {}),
        "benchmarks": _latest_nonempty(boards, "benchmarks", []),
        "exits": _dedupe_exits([x for b in boards for x in (b.get("exits") or [])]),
        "positions_count": max([int(b.get("positions_count") or 0) for b in boards] or [0]),
        "forecast_config": _latest_nonempty(boards, "forecast_config", {}),
        "regime": _latest_nonempty(boards, "regime", {}),
        "watchlist": items,
    }


def _scan_day(watchlist: dict) -> str:
    raw = watchlist.get("generated_at")
    if isinstance(raw, str) and len(raw) >= 10:
        return raw[:10]
    return datetime.now(timezone.utc).date().isoformat()


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return s[:60] or "bucket"


def _balanced_score(item: dict) -> float:
    try:
        return float(item["opportunity"]["profiles"]["balanced"]["score"])
    except Exception:  # noqa: BLE001
        return float(item.get("score") or 0)


def _profile_rank(item: dict, profile: str) -> int:
    try:
        return int(item["opportunity"]["profiles"][profile]["rank"])
    except Exception:  # noqa: BLE001
        return 9999


def _sort_key(item: dict) -> tuple:
    return (
        _profile_rank(item, "balanced"),
        -_balanced_score(item),
        -float(item.get("score") or 0),
        str(item.get("symbol") or ""),
    )


def _rerank_profiles(items: list[dict]) -> None:
    try:
        from scanner import opportunity_ranker
        opportunity_ranker.apply_ranks(items)
    except Exception:  # noqa: BLE001
        return


def _latest_nonempty(boards: list[dict], key: str, default):
    for board in reversed(boards):
        val = board.get(key)
        if val:
            return val
    return default


def _dedupe_exits(exits: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for ex in exits:
        sym = str(ex.get("symbol") or "").upper()
        if sym and sym in seen:
            continue
        if sym:
            seen.add(sym)
        out.append(ex)
    return out
