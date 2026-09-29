import os
import sys
import datetime

# Parse --config BEFORE importing config, so the config module sees TRANSLATOR_CONFIG.
for _i, _arg in enumerate(sys.argv):
    if _arg == "--config" and _i + 1 < len(sys.argv):
        os.environ["TRANSLATOR_CONFIG"] = sys.argv[_i + 1]

# Parse --reload flag (boolean, no value)
_reload = "--reload" in sys.argv

from contextlib import asynccontextmanager
from typing import Any
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

import logging

logger = logging.getLogger(__name__)

import cache_manager
import config
import stats_manager
from translator import LLMTranslator, TranslationError

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_provider = os.environ.get("TRANSLATOR_PROVIDER")

for i, arg in enumerate(sys.argv):
    if arg == "--provider" and i + 1 < len(sys.argv):
        _provider = sys.argv[i + 1]

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
        try:
            raw: Any = await request.json()
        except Exception as e:
            logger.warning("Failed to parse JSON body: %s", e)
            raise HTTPException(400, detail="Invalid JSON body")
        if not isinstance(raw, dict):
            raise HTTPException(400, detail="JSON body must be an object")
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
            logger.debug(
                "Field '%s' is %s, converting to string", key, type(val).__name__
            )
            return str(val)
        if val is not None:
            logger.warning(
                "Field '%s' has unexpected type %s: %r", key, type(val).__name__, val
            )
        return default

    q = _str("q")
    source = _str("source", "auto")
    target = _str("target")

    if not q.strip():
        logger.debug("Empty q='%s', returning empty translation", q.strip())
        return {"translatedText": ""}
    if not target.strip():
        logger.warning(
            "Bad request — q=%r source=%r target=%r raw keys=%s",
            q,
            source,
            target,
            list(raw.keys()) if hasattr(raw, "keys") else type(raw).__name__,
        )
        raise HTTPException(400, detail="target is required")

    # Not stripped: SillyTavern splits a message at every markdown image and
    # re-inserts the links itself with no separator, so the trailing blank line
    # we were sent is the only thing keeping the image on its own line. The
    # cache key is computed from the stripped text either way.
    payload = q
    # An image count in the request log settles, without guessing, whether a
    # missing image was lost here or never sent by the client: the cached
    # source_text is the request verbatim.
    logger.info(
        "Translation request: %d chars, %d markdown image(s), %d link(s) "
        "(source=%s target=%s)",
        len(payload),
        payload.count("!["),
        payload.count("](") - payload.count("!["),
        source,
        target,
    )

    try:
        return await translator.translate(payload, source, target.strip())
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


static_dir = os.path.join(os.path.dirname(__file__), "static")


if os.path.isdir(static_dir):

    @app.get("/stats")
    async def stats_page():
        return FileResponse(os.path.join(static_dir, "stats.html"))


@app.get("/stats/api")
async def stats_api(
    from_date: str | None = Query(None, alias="from"),
    to_date: str | None = Query(None, alias="to"),
):
    custom_start = custom_end = None
    if bool(from_date) != bool(to_date):
        raise HTTPException(400, detail="Both 'from' and 'to' are required together")
    if from_date and to_date:
        try:
            d1 = datetime.date.fromisoformat(from_date)
            d2 = datetime.date.fromisoformat(to_date)
        except ValueError:
            raise HTTPException(400, detail="Dates must be in YYYY-MM-DD format")
        if d1 > d2:
            raise HTTPException(400, detail="'from' date must be <= 'to' date")
        custom_start = datetime.datetime.combine(d1, datetime.time.min).timestamp()
        custom_end = datetime.datetime.combine(
            d2 + datetime.timedelta(days=1), datetime.time.min
        ).timestamp()
    return stats_manager.build_stats(custom_start=custom_start, custom_end=custom_end)


if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def root():
        return FileResponse(os.path.join(static_dir, "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=_reload)
