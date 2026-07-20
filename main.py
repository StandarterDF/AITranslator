import os
import sys
from typing import Any
from fastapi import FastAPI, HTTPException, Request

import logging

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import cache_manager
import config
from translator import LLMTranslator, TranslationError

_provider = os.environ.get("TRANSLATOR_PROVIDER")
_preset_name: str | None = os.environ.get("TRANSLATOR_PRESET")

for i, arg in enumerate(sys.argv):
    if arg == "--provider" and i + 1 < len(sys.argv):
        _provider = sys.argv[i + 1]
    if arg == "--preset" and i + 1 < len(sys.argv):
        _preset_name = sys.argv[i + 1]

if _preset_name is not None:
    loaded = config.load_preset(_preset_name)
    if loaded is None:
        print(f"Error: preset '{_preset_name}' not found")
        sys.exit(1)
    config.apply_preset(loaded)
    logger.info("Loaded preset: %s", loaded.get("name", _preset_name))
else:
    logger.info("No preset specified, using defaults from config.py")

try:
    translator = LLMTranslator(_provider)
except ValueError as e:
    print(f"Configuration error: {e}")
    sys.exit(1)

app = FastAPI(title="AILibreTranslater")


@app.post("/translate")
async def translate(request: Request):
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        raw: Any = await request.json()
    else:
        try:
            raw = await request.form()
        except Exception as e:
            logger.warning("Failed to parse form body: %s", e)
            raise HTTPException(400, detail="Invalid form data")

    def _str(key: str, default: str = "") -> str:
        val = raw.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, (int, float, bool)):
            logger.debug("Field '%s' is %s, converting to string", key, type(val).__name__)
            return str(val)
        if val is not None:
            logger.warning("Field '%s' has unexpected type %s: %r", key, type(val).__name__, val)
        return default

    q = _str("q")
    source = _str("source", "auto")
    target = _str("target")

    if not q.strip():
        logger.debug("Empty q='%s', returning empty translation", q.strip())
        return {"translatedText": ""}
    if not target.strip():
        logger.warning("Bad request — q=%r source=%r target=%r raw keys=%s",
                       q, source, target, list(raw.keys()) if hasattr(raw, 'keys') else type(raw).__name__)
        raise HTTPException(400, detail="target is required")

    try:
        return await translator.translate(q.strip(), source, target.strip())
    except TranslationError as e:
        raise HTTPException(e.status_code, detail=e.message)


@app.get("/cache")
async def list_cache_entries():
    entries = cache_manager.list_cache()
    return {"entries": entries, "total": len(entries)}


@app.delete("/cache/{hash_key}")
async def delete_cache_entry(hash_key: str):
    if not cache_manager.delete_cache(hash_key):
        raise HTTPException(404, detail="Cache entry not found")
    return {"detail": "Cache entry deleted"}


@app.post("/cache/{hash_key}/invalidate")
async def invalidate_cache_entry(hash_key: str):
    if not cache_manager.invalidate_cache(hash_key):
        raise HTTPException(404, detail="Cache entry not found")
    return {"detail": "Cache entry invalidated"}


@app.delete("/cache")
async def clear_all_cache():
    count = cache_manager.clear_cache()
    return {"detail": f"Cleared {count} cache entries"}


if __name__ == "__main__":
    import uvicorn

    if _preset_name is None and "--preset" not in sys.argv:
        _preset_name = config.choose_preset_interactive()

    if _preset_name is not None:
        os.environ["TRANSLATOR_PRESET"] = _preset_name

    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=True)
