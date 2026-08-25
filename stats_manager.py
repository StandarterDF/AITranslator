import datetime
import json
import logging
import threading
import time
from pathlib import Path

import cache_manager

logger = logging.getLogger(__name__)

SESSION_START = time.time()

STATS_DIR = Path(__file__).parent / "stats"
EVENTS_FILE = STATS_DIR / "events.jsonl"

_lock = threading.Lock()

LENGTH_BUCKETS = [
    ("0-99", 0, 100),
    ("100-499", 100, 500),
    ("500-999", 500, 1000),
    ("1k-4999", 1000, 5000),
    ("5000+", 5000, None),
]


def _ensure_stats_dir():
    STATS_DIR.mkdir(parents=True, exist_ok=True)


def log_event(
    event_type: str,
    *,
    hash_key: str | None = None,
    source: str = "",
    target: str = "",
    step: str | None = None,
    steps_failed: list[str] | None = None,
    latency_s: float | None = None,
    input_chars: int = 0,
    output_chars: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    preview: str = "",
    error: str | None = None,
) -> None:
    record: dict = {"ts": round(time.time(), 3), "type": event_type}
    if hash_key:
        record["hash"] = hash_key
    if source:
        record["source"] = source
    if target:
        record["target"] = target
    if step:
        record["step"] = step
    if steps_failed:
        record["steps_failed"] = steps_failed
    if latency_s is not None:
        record["latency_s"] = round(latency_s, 3)
    if input_chars:
        record["input_chars"] = input_chars
    if output_chars:
        record["output_chars"] = output_chars
    if prompt_tokens:
        record["prompt_tokens"] = prompt_tokens
    if completion_tokens:
        record["completion_tokens"] = completion_tokens
    if preview:
        record["preview"] = preview[:80]
    if error:
        record["error"] = error[:300]
    try:
        _ensure_stats_dir()
        line = json.dumps(record, ensure_ascii=False)
        with _lock:
            with EVENTS_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        logger.debug("Stats event logged: %s", event_type)
    except OSError as e:
        logger.warning("Failed to write stats event: %s", e)


def read_events() -> list[dict]:
    if not EVENTS_FILE.exists():
        return []
    events: list[dict] = []
    try:
        with EVENTS_FILE.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        events.append(data)
                    else:
                        logger.warning("Skipping non-object stats line %d", line_no)
                except ValueError:
                    logger.warning("Skipping corrupt stats line %d", line_no)
    except OSError as e:
        logger.warning("Failed to read stats events: %s", e)
    return events


def _day_key(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def _local_midnight(days_back: int) -> float:
    lt = time.localtime()
    d = datetime.date(lt.tm_year, lt.tm_mon, lt.tm_mday) - datetime.timedelta(
        days=days_back
    )
    return time.mktime(d.timetuple())


def summarize(events: list[dict]) -> dict:
    n_success = sum(1 for e in events if e.get("type") == "success")
    n_cached = sum(1 for e in events if e.get("type") == "cache_hit")
    n_errors = sum(1 for e in events if e.get("type") == "error")
    latencies = [e["latency_s"] for e in events if e.get("latency_s") is not None]
    lookups = n_success + n_cached
    return {
        "requests": len(events),
        "success": n_success,
        "cache_hits": n_cached,
        "errors": n_errors,
        "hit_rate": round(n_cached / lookups, 4) if lookups else None,
        "avg_latency_s": (
            round(sum(latencies) / len(latencies), 3) if latencies else None
        ),
        "prompt_tokens": sum(e.get("prompt_tokens", 0) for e in events),
        "completion_tokens": sum(e.get("completion_tokens", 0) for e in events),
        "chars_in": sum(int(e.get("input_chars", 0)) for e in events),
        "chars_out": sum(int(e.get("output_chars", 0)) for e in events),
    }


def _bucket_index(n: int) -> int:
    for i, (_, lo, hi) in enumerate(LENGTH_BUCKETS):
        if n >= lo and (hi is None or n < hi):
            return i
    return len(LENGTH_BUCKETS) - 1


def _aggregate(events: list[dict]) -> dict:
    pairs: dict[str, int] = {}
    hourly = [0] * 24
    buckets = [0] * len(LENGTH_BUCKETS)
    largest: list[dict] = []

    for e in events:
        etype = e.get("type", "")
        ts = e.get("ts", 0)
        hourly[time.localtime(ts).tm_hour] += 1
        src = e.get("source", "")
        tgt = e.get("target", "")
        if src or tgt:
            pk = f"{src}\u2192{tgt}"
            pairs[pk] = pairs.get(pk, 0) + 1
        ic = int(e.get("input_chars", 0))
        if etype != "error":
            buckets[_bucket_index(ic)] += 1
            largest.append(
                {
                    "ts": ts,
                    "pair": f"{src}\u2192{tgt}",
                    "chars": ic,
                    "preview": e.get("preview", ""),
                    "backfill": bool(e.get("backfill")),
                }
            )

    largest.sort(key=lambda x: x["chars"], reverse=True)
    top_pairs = sorted(pairs.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "lang_pairs": [{"pair": p, "count": n} for p, n in top_pairs],
        "pair_count": len(pairs),
        "hourly": hourly,
        "length_buckets": [
            {"label": LENGTH_BUCKETS[i][0], "count": buckets[i]}
            for i in range(len(LENGTH_BUCKETS))
        ],
        "largest": largest[:10],
    }


def build_stats(
    custom_start: float | None = None, custom_end: float | None = None
) -> dict:
    events = read_events()

    success_hashes = {
        e.get("hash") for e in events if e.get("type") == "success" and e.get("hash")
    }

    cache_entries = cache_manager.list_cache()
    backfill: list[dict] = []
    for c in cache_entries:
        if c["hash"] in success_hashes:
            continue
        backfill.append(
            {
                "ts": c["created_at"],
                "type": "success",
                "hash": c["hash"],
                "source": c["source"],
                "target": c["target"],
                "input_chars": c["size"],
                "preview": c["source_text_preview"],
                "backfill": True,
            }
        )

    combined = sorted(events + backfill, key=lambda e: e.get("ts", 0))

    t = summarize(events)

    range_defs = {
        "1d": _local_midnight(0),
        "7d": _local_midnight(6),
        "30d": _local_midnight(29),
        "all": 0.0,
    }
    ranges = {}
    for rkey, cut in range_defs.items():
        evts = [e for e in combined if e.get("ts", 0) >= cut]
        ranges[rkey] = {
            **summarize(evts),
            **_aggregate(evts),
            "since": time.strftime("%Y-%m-%d", time.localtime(cut)) if cut else None,
        }

    if custom_start is not None and custom_end is not None:
        evts = [e for e in combined if custom_start <= e.get("ts", 0) < custom_end]
        ranges["custom"] = {
            **summarize(evts),
            **_aggregate(evts),
            "since": time.strftime("%Y-%m-%d", time.localtime(custom_start)),
            "until": time.strftime(
                "%Y-%m-%d", time.localtime(max(0.0, custom_end - 1))
            ),
        }

    timeline: dict[str, dict] = {}
    chars_in = 0
    chars_out = 0

    for e in combined:
        etype = e.get("type", "")
        ts = e.get("ts", 0)
        day = _day_key(ts)
        slot = timeline.setdefault(
            day, {"date": day, "success": 0, "cache_hit": 0, "error": 0}
        )
        if etype in slot:
            slot[etype] += 1
        chars_in += int(e.get("input_chars", 0))
        chars_out += int(e.get("output_chars", 0))

    days = sorted(timeline.keys())
    filled: list[dict] = []
    if days:
        first = time.strptime(days[0], "%Y-%m-%d")
        last = time.strptime(days[-1], "%Y-%m-%d")
        cur_ts = time.mktime(first)
        end = time.mktime(last)
        limit = cur_ts - 400 * 86400
        while cur_ts <= end and cur_ts >= limit:
            key = time.strftime("%Y-%m-%d", time.localtime(cur_ts))
            filled.append(
                timeline.get(
                    key,
                    {"date": key, "success": 0, "cache_hit": 0, "error": 0},
                )
            )
            cur_ts += 86400

    recent = [
        {
            "ts": e.get("ts", 0),
            "type": e.get("type", ""),
            "source": e.get("source", ""),
            "target": e.get("target", ""),
            "step": e.get("step"),
            "steps_failed": e.get("steps_failed"),
            "latency_s": e.get("latency_s"),
            "input_chars": e.get("input_chars", 0),
            "prompt_tokens": e.get("prompt_tokens", 0),
            "completion_tokens": e.get("completion_tokens", 0),
            "preview": e.get("preview", ""),
            "error": e.get("error"),
        }
        for e in reversed(events[-20:])
    ]

    session_events = [e for e in events if e.get("ts", 0) >= SESSION_START]

    session_slots: dict[int, dict] = {}
    for e in session_events:
        h = int(e.get("ts", 0) // 3600) * 3600
        slot = session_slots.setdefault(h, {"success": 0, "cache_hit": 0, "error": 0})
        etype = e.get("type", "")
        if etype in slot:
            slot[etype] += 1

    now_hour = int(time.time() // 3600) * 3600
    start_hour = int(SESSION_START // 3600) * 3600
    min_hour = now_hour - 167 * 3600
    session_timeline = []
    h = start_hour
    while h <= now_hour:
        counts = session_slots.get(h)
        if h >= min_hour:
            session_timeline.append(
                {"ts": h, **(counts or {"success": 0, "cache_hit": 0, "error": 0})}
            )
        h += 3600

    return {
        "totals": {
            "requests": t["requests"],
            "success": t["success"],
            "cache_hits": t["cache_hits"],
            "errors": t["errors"],
            "hit_rate": t["hit_rate"],
            "avg_latency_s": t["avg_latency_s"],
            "prompt_tokens": t["prompt_tokens"],
            "completion_tokens": t["completion_tokens"],
            "chars_in": chars_in,
            "chars_out": chars_out,
            "first_activity": days[0] if days else None,
        },
        "session": {
            **summarize(session_events),
            **_aggregate(session_events),
            "started_at": SESSION_START,
        },
        "session_timeline": session_timeline,
        "ranges": ranges,
        "cache": {
            "entries": len(cache_entries),
            "invalid": sum(1 for c in cache_entries if c.get("invalid")),
        },
        "timeline": filled,
        "recent": recent,
    }
