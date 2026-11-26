"""
Cost guard (tiêu chí 8).

  • Cộng dồn chi phí LLM (tính theo token) vào Redis — dùng chung cho mọi worker / instance
  • Tổng chi phí trong ngày vượt DAILY_BUDGET_USD, hoặc trong tháng vượt MONTHLY_BUDGET_USD → HTTP 402

Key theo ngày / tháng (UTC) → sang ngày / tháng mới tự bắt đầu lại từ 0, không cần cron.
"""
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAY_TTL = 2 * 24 * 3600
MONTH_TTL = 32 * 24 * 3600


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return f"cost:day:{now:%Y-%m-%d}", f"cost:month:{now:%Y-%m}"


def estimate_tokens(text: str) -> int:
    """Ước lượng thô ~ 4 ký tự / token (mock LLM không trả số token thật)."""
    return max(1, len(text) // 4)


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    day_key, month_key = _keys()
    day_spent, month_spent = (float(v or 0) for v in r.mget(day_key, month_key))
    if day_spent >= settings.daily_budget_usd:
        raise HTTPException(status_code=402, detail={
            "error": "Daily budget exceeded", "spent_usd": round(day_spent, 6),
            "budget_usd": settings.daily_budget_usd, "resets": "00:00 UTC"})
    if month_spent >= settings.monthly_budget_usd:
        raise HTTPException(status_code=402, detail={
            "error": "Monthly budget exceeded", "spent_usd": round(month_spent, 6),
            "budget_usd": settings.monthly_budget_usd, "resets": "first day of month (UTC)"})


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = input_tokens / 1000 * PRICE_INPUT_PER_1K + output_tokens / 1000 * PRICE_OUTPUT_PER_1K
    day_key, month_key = _keys()
    pipe = r.pipeline(transaction=True)
    pipe.incrbyfloat(day_key, cost)
    pipe.expire(day_key, DAY_TTL)
    pipe.incrbyfloat(month_key, cost)
    pipe.expire(month_key, MONTH_TTL)
    pipe.execute()
    return cost
