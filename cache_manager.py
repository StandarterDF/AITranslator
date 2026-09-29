import hashlib
import json
import logging
import time
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / "cache"


def _ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(source: str, target: str, text: str) -> str:
    source = (
        "auto" if source.strip().lower() in ("", "auto") else source.strip().lower()
    )
    target = target.strip().lower()
    text = (
        unicodedata.normalize("NFC", text)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .strip()
    )
    raw = f"{source}||{target}||{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_key(source: str, target: str, text: str) -> str:
    return _cache_key(source, target, text)


def _file_path(hash_key: str) -> Path:
    return CACHE_DIR / f"{hash_key}.json"


def get_entry(source: str, target: str, text: str) -> dict | None:
    """Read a raw cache entry, including the translator version stamp.

    Returns None when there is no entry, it is marked invalid, or it cannot be
    parsed.  The caller gets the whole dict so it can inspect `version` without
    a second read.
    """
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
        return data
    except (json.JSONDecodeError, KeyError, OSError) as e:
        logger.warning("Failed to read cache entry %s: %s", key[:12], e)
        return None


def get_cache(source: str, target: str, text: str) -> str | None:
    data = get_entry(source, target, text)
    if data is None:
        return None
    return data.get("translated_text")


def get_version(entry: dict) -> int:
    """Version stamp of an entry; 0 when it was written before versioning."""
    version = entry.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        return 0
    return version


def set_version(hash_key: str, version: int) -> bool:
    """Stamp an existing entry with the current translator version.

    Only the ``version`` field is touched, so ``created_at`` — and with it the
    order of the ``GET /cache`` listing — stays as it was.  A no-op (returns
    False) when the entry already carries that version or does not exist.
    """
    path = _file_path(hash_key)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text("utf-8"))
        if get_version(data) == version:
            return False
        data["version"] = version
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        logger.debug("Cache entry %s stamped with version %d", hash_key[:12], version)
        return True
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to stamp version for %s: %s", hash_key[:12], e)
        return False


def set_cache(
    source: str,
    target: str,
    text: str,
    translated_text: str,
    version: int = 0,
):
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
        "version": version,
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
    for p in CACHE_DIR.glob("*.json"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        try:
            data = json.loads(p.read_text("utf-8"))
            entries.append(
                {
                    "hash": data.get("hash", p.stem),
                    "source": data.get("source", ""),
                    "target": data.get("target", ""),
                    "source_text_preview": data.get("source_text", "")[:80],
                    "translated_text_preview": data.get("translated_text", "")[:80],
                    "created_at": data.get("created_at", mtime),
                    "size": len(data.get("source_text", "")),
                    "version": get_version(data),
                    "invalid": data.get("invalid", False),
                }
            )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to read %s: %s", p.name, e)
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return entries
