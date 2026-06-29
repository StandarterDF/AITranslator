import os
import sys
from typing import Any
from fastapi import FastAPI, HTTPException, Request

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from translator import LLMTranslator, TranslationError

_provider = os.environ.get("TRANSLATOR_PROVIDER")
for i, arg in enumerate(sys.argv):
    if arg == "--provider" and i + 1 < len(sys.argv):
        _provider = sys.argv[i + 1]
        break

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
        raw = await request.form()

    def _str(key: str, default: str = "") -> str:
        val = raw.get(key)
        if isinstance(val, str):
            return val
        return default

    q = _str("q")
    source = _str("source", "auto")
    target = _str("target")

    if not q.strip():
        raise HTTPException(400, detail="q is required and must not be empty")
    if not target.strip():
        raise HTTPException(400, detail="target is required")

    try:
        return await translator.translate(q.strip(), source, target.strip())
    except TranslationError as e:
        raise HTTPException(e.status_code, detail=e.message)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5555, reload=True)
