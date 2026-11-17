"""Local HTTP API for the Laya decision engine (for n8n on the same machine).

Run (inside .venv-laya, from project root):
  PYTHONPATH=src python -m decision_engine.api

Security:
- Binds to 127.0.0.1 by default. A non-loopback host is refused unless
  LAYA_API_ALLOW_REMOTE=1 (requires a separately reviewed network design).
- Every endpoint except /health needs `Authorization: Bearer <LAYA_API_TOKEN>`.
  The server refuses to start without a token.
- Input is schema-validated (closed task names, <= 2,000 chars), request bodies are capped,
  one inference runs at a time, and each request has a timeout.
- Responses and logs never echo the input text.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .confidence_policy import TaskPolicy, load_policy
from .decision_schemas import Decision, PredictRequest, TaskName
from .laya_engine import DecisionEngine

log = logging.getLogger("decision_engine.api")

MAX_BODY_BYTES = 64 * 1024
MAX_EVAL_ITEMS = 50


class EvalItem(BaseModel):
    task: TaskName
    text: str = Field(min_length=1, max_length=2000)
    label: str = Field(min_length=1, max_length=64)


class EvaluateRequest(BaseModel):
    items: list[EvalItem] = Field(min_length=1, max_length=MAX_EVAL_ITEMS)


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_app(manager: Any = None, policy: dict[str, TaskPolicy] | None = None,
               token: str | None = None, timeout_s: float | None = None, warmup: bool = True) -> FastAPI:
    api_token = token if token is not None else os.getenv("LAYA_API_TOKEN", "")
    if len(api_token) < 16:
        raise RuntimeError("LAYA_API_TOKEN must be set (>= 16 chars) before starting the Laya API")
    req_timeout = timeout_s if timeout_s is not None else float(os.getenv("LAYA_API_TIMEOUT_S", "30"))
    state: dict[str, Any] = {"ready": False, "engine": None, "load_error": None}
    sem = asyncio.Semaphore(1)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        mm = manager
        if mm is None:
            from .model_manager import ModelManager

            mm = ModelManager()
        try:
            if warmup:
                # Load weights once at startup, off the event loop.
                await asyncio.to_thread(mm.predict, "warm up", {"w": {"type": "noul", "instructions": "Is this a test?"}})
            state["engine"] = DecisionEngine(mm, policy or load_policy())
            state["ready"] = True
            log.info("laya api ready checkpoint=%s", getattr(mm, "checkpoint", None))
        except Exception as exc:
            state["load_error"] = type(exc).__name__
            log.error("laya model load failed: %s", exc)
        yield
        log.info("laya api shutting down")
        state["ready"] = False

    app = FastAPI(title="Astra Laya Decision Engine", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = uuid.uuid4().hex[:16]
        cl = request.headers.get("content-length")
        if cl is not None and (not cl.isdigit() or int(cl) > MAX_BODY_BYTES):
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        t0 = time.perf_counter()
        response = await call_next(request)
        log.info('{"event":"http","request_id":"%s","method":"%s","path":"%s","status":%d,"ms":%.1f}',
                 rid, request.method, request.url.path, response.status_code, (time.perf_counter() - t0) * 1000)
        return response

    def auth(authorization: str | None = Header(default=None)) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        if not hmac.compare_digest(authorization[7:].encode(), api_token.encode()):
            raise HTTPException(status_code=401, detail="invalid token")

    def engine() -> DecisionEngine:
        if not state["ready"]:
            raise HTTPException(status_code=503, detail="model not ready")
        return state["engine"]

    async def run_decision(eng: DecisionEngine, req: PredictRequest) -> Decision:
        async with sem:
            try:
                return await asyncio.wait_for(asyncio.to_thread(eng.decide, req), timeout=req_timeout)
            except asyncio.TimeoutError:
                log.error("laya inference timeout request_id=%s", req.request_id)
                raise HTTPException(status_code=504, detail="inference timeout") from None

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ready" if state["ready"] else ("error" if state["load_error"] else "loading")}

    @app.get("/model-info", dependencies=[Depends(auth)])
    async def model_info() -> dict:
        eng = engine()
        info = eng.manager.info() if hasattr(eng.manager, "info") else {"checkpoint": getattr(eng.manager, "checkpoint", None)}
        info["policy"] = {t: {"enabled": p.enabled, "high": p.high, "medium": p.medium} for t, p in eng.policy.items()}
        return info

    @app.post("/predict", dependencies=[Depends(auth)], response_model=Decision)
    async def predict(req: PredictRequest) -> Decision:
        return await run_decision(engine(), req)

    @app.post("/evaluate", dependencies=[Depends(auth)])
    async def evaluate(body: EvaluateRequest) -> dict:
        eng = engine()
        rows = []
        for i, item in enumerate(body.items):
            d = await run_decision(eng, PredictRequest(task=item.task, text=item.text, request_id=f"eval-{i}"))
            rows.append({"index": i, "expected": item.label, "predicted": d.label, "confidence": d.confidence,
                         "source": d.source, "correct": d.label == item.label})
        n = len(rows)
        return {"n": n, "accuracy": round(sum(r["correct"] for r in rows) / n, 3), "items": rows}

    return app


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    host = os.getenv("LAYA_API_HOST", "127.0.0.1")
    port = int(os.getenv("LAYA_API_PORT", "8765"))
    if not _is_loopback(host) and os.getenv("LAYA_API_ALLOW_REMOTE") != "1":
        raise SystemExit(f"refusing to bind {host}: only loopback is allowed (see docs/26-laya-n8n-integration.md)")
    uvicorn.run(create_app(), host=host, port=port, log_level="info", timeout_graceful_shutdown=10)


if __name__ == "__main__":
    main()
