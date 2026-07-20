import os
import sys
from contextlib import asynccontextmanager
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


def _choose_preset_interactive() -> str:
    presets = config.list_presets()
    if not presets:
        return "default"

    print("\nAvailable presets:")
    for i, p in enumerate(presets, 1):
        desc = p["description"]
        print(f"  {i}. {p['name']}" + (f" — {desc}" if desc else ""))

    while True:
        try:
            choice = input(f"\nSelect preset [1-{len(presets)}] (default 1): ").strip()
            if not choice:
                choice = "1"
            idx = int(choice) - 1
            if 0 <= idx < len(presets):
                print(f"Selected: {presets[idx]['name']}\n")
                return presets[idx]["key"]
            print(f"Please enter a number between 1 and {len(presets)}")
        except (ValueError, EOFError, KeyboardInterrupt):
            print()
            return presets[0]["key"] if presets else "default"


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await translator.aclose()


app = FastAPI(title="AILibreTranslater", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


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


if __name__ == "__main__":
    import uvicorn

    if _preset_name is None and "--preset" not in sys.argv:
        _preset_name = _choose_preset_interactive()

    if _preset_name is not None:
        os.environ["TRANSLATOR_PRESET"] = _preset_name

    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=True)
