import hashlib
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache"


def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(source: str, target: str, text: str) -> str:
    raw = f"{source}||{target}||{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_path(hash_key: str) -> Path:
    return CACHE_DIR / f"{hash_key}.json"


def get_cache(source: str, target: str, text: str) -> str | None:
    key = _cache_key(source, target, text)
    path = _file_path(key)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
        if data.get("invalid"):
            logger.debug("Cache entry %s is marked as invalid, skipping", key[:12])
            return None
        logger.info("Cache hit for key %s", key[:12])
        return data["translated_text"]
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("Failed to read cache entry %s: %s", key[:12], e)
        return None


def set_cache(source: str, target: str, text: str, translated_text: str):
    _ensure_cache_dir()
    key = _cache_key(source, target, text)
    path = _file_path(key)
    data = {
        "hash": key,
        "source": source,
        "target": target,
        "source_text": text,
        "translated_text": translated_text,
        "created_at": time.time(),
        "invalid": False,
    }
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        logger.info("Cached translation %s", key[:12])
    except OSError as e:
        logger.warning("Failed to write cache entry %s: %s", key[:12], e)


def invalidate_cache(hash_key: str) -> bool:
    path = _file_path(hash_key)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
        data["invalid"] = True
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        logger.info("Invalidated cache entry %s", hash_key[:12])
        return True
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to invalidate cache entry %s: %s", hash_key[:12], e)
        return False


def delete_cache(hash_key: str) -> bool:
    path = _file_path(hash_key)
    if not path.exists():
        return False
    try:
        path.unlink()
        logger.info("Deleted cache entry %s", hash_key[:12])
        return True
    except OSError as e:
        logger.warning("Failed to delete cache entry %s: %s", hash_key[:12], e)
        return False


def clear_cache() -> int:
    _ensure_cache_dir()
    count = 0
    for p in CACHE_DIR.glob("*.json"):
        try:
            p.unlink()
            count += 1
        except OSError as e:
            logger.warning("Failed to delete %s: %s", p.name, e)
    logger.info("Cleared cache: %d files removed", count)
    return count


def list_cache() -> list[dict]:
    _ensure_cache_dir()
    entries = []
    for p in sorted(CACHE_DIR.glob("*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(p.read_text("utf-8"))
            entries.append({
                "hash": data.get("hash", p.stem),
                "source": data.get("source", ""),
                "target": data.get("target", ""),
                "source_text_preview": data.get("source_text", "")[:80],
                "translated_text_preview": data.get("translated_text", "")[:80],
                "created_at": data.get("created_at", 0),
                "size": len(data.get("source_text", "")),
                "invalid": data.get("invalid", False),
            })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", p.name, e)
    return entries
