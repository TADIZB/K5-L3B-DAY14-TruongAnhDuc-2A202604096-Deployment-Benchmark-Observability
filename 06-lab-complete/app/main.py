"""
Production AI Agent — Part 6 Final Project

Chạy:  uvicorn app.main:app --workers 2
Kiểm tra:  python check_production_ready.py

Luồng /ask:  X-API-Key (401) + validate body (422) → rate limit (429) → budget (402)
             → LLM → ghi chi phí.  Redis lỗi → 503, lỗi khác → 500 (không lộ stack trace).
"""
import json
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_tokens, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


# ─────────────────────────────────────────────────────────
# Structured logging (tiêu chí 10): mỗi dòng log = 1 JSON object
# ─────────────────────────────────────────────────────────
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # field thêm qua logger.info(..., extra={...})
        for k, v in vars(record).items():
            if k not in _STD_ATTRS and not k.startswith("_"):
                entry[k] = v
        if record.exc_info:
            entry["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return json.dumps(entry, ensure_ascii=False, default=str)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
# force=True: ghi đè cấu hình cũ (bài học Part 1: logging.warning() gọi trước basicConfig
# làm basicConfig mất tác dụng)
logging.basicConfig(level=settings.log_level, handlers=[_handler], force=True)
logger = logging.getLogger("agent")


def log_event(event: str, level: int = logging.INFO, **fields) -> None:
    logger.log(level, event, extra={"event": event, **fields})


# ─────────────────────────────────────────────────────────
# Lifespan + graceful shutdown (tiêu chí 11)
# ─────────────────────────────────────────────────────────
STATE = {"ready": False, "in_flight": 0, "started": time.time()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: KHÔNG bắt buộc Redis — container phải khởi động được khi chưa có Redis
    STATE["ready"] = True
    log_event("startup", environment=settings.environment, version=settings.app_version,
              port=settings.port, redis_ok=redis_healthy(),
              rate_limit_per_minute=settings.rate_limit_per_minute)
    yield
    # Shutdown: uvicorn nhận SIGTERM → ngừng nhận kết nối mới → chờ request đang chạy xong
    # → chạy phần này. Không tự đăng ký signal handler để khỏi chặn handler của uvicorn.
    STATE["ready"] = False
    log_event("shutdown", in_flight=STATE["in_flight"],
              uptime_s=round(time.time() - STATE["started"], 1))
    try:
        r.close()
    except Exception:  # noqa: BLE001 — đang tắt, lỗi đóng kết nối không quan trọng
        pass


app = FastAPI(
    title="Production AI Agent",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None if settings.environment == "production" else "/docs",
    redoc_url=None,
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    STATE["in_flight"] += 1
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        STATE["in_flight"] -= 1
        if request.url.path not in ("/health", "/ready"):  # probe gọi liên tục, không log
            log_event("request", method=request.method, path=request.url.path, status=status,
                      ms=round((time.perf_counter() - started) * 1000, 1), request_id=request_id)


# ─────────────────────────────────────────────────────────
# Xử lý lỗi: mã lỗi rõ ràng, không lộ stack trace
# ─────────────────────────────────────────────────────────
@app.exception_handler(redis.RedisError)
async def redis_error_handler(request: Request, exc: redis.RedisError):
    log_event("redis_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Service temporarily unavailable (state store)."},
                        headers={"Retry-After": "5"})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    log_event("unhandled_error", logging.ERROR, path=request.url.path, error=type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# ─────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=128)


@app.get("/")
def root():
    return {"app": "Production AI Agent", "version": settings.app_version,
            "environment": settings.environment}


@app.get("/health")
def health():
    """Liveness (tiêu chí 4): luôn 200 khi process còn chạy, KHÔNG phụ thuộc Redis."""
    return {"status": "ok", "version": settings.app_version,
            "uptime_seconds": round(time.time() - STATE["started"], 1),
            "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/ready")
def ready():
    """Readiness (tiêu chí 5): 503 khi đang tắt hoặc Redis không kết nối được."""
    if not STATE["ready"]:
        raise HTTPException(status_code=503, detail="Shutting down")
    if not redis_healthy():
        raise HTTPException(status_code=503, detail="Redis not reachable")
    return {"ready": True, "redis": "ok"}


# `def` thường (không async): mock LLM dùng time.sleep, FastAPI chạy hàm này trong threadpool
# nên không chặn event loop (bài học Part 5).
@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)          # 429
    check_budget()                     # 402
    started = time.perf_counter()
    answer = llm_ask(body.question)
    cost = record_cost(estimate_tokens(body.question), estimate_tokens(answer))
    log_event("llm_call", llm_ms=round((time.perf_counter() - started) * 1000, 1),
              question_chars=len(body.question), cost_usd=round(cost, 8))
    return {"question": body.question, "answer": answer}
