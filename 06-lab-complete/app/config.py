"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường (tiêu chí 9).

  • Mọi giá trị lấy từ env, có mặc định hợp lý khi chạy local.
  • Không có secret nào trong code: AGENT_API_KEY không có giá trị mặc định.
  • Chạy local có thể đặt biến trong file .env (đã nằm trong .gitignore và .dockerignore);
    biến môi trường thật (platform, docker, shell) luôn được ưu tiên hơn .env.
  • Danh sách đầy đủ các biến: .env.example
"""
import os
from dataclasses import dataclass, field

try:  # .env chỉ để tiện chạy local; trong container / trên cloud không có file này
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:  # pragma: no cover
    pass


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


@dataclass
class Settings:
    # Server
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "1.0.0"))

    # Security — secret, KHÔNG có giá trị mặc định
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))

    # State (rate limit, cost) nằm trong Redis
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    # Giới hạn
    rate_limit_per_minute: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MINUTE", 10))
    daily_budget_usd: float = field(default_factory=lambda: _env_float("DAILY_BUDGET_USD", 1.0))
    monthly_budget_usd: float = field(default_factory=lambda: _env_float("MONTHLY_BUDGET_USD", 10.0))

    def validate(self) -> "Settings":
        """Fail fast: production mà thiếu API key thì không cho khởi động."""
        if self.environment == "production" and not self.agent_api_key:
            raise ValueError("AGENT_API_KEY must be set when ENVIRONMENT=production")
        if self.rate_limit_per_minute < 1:
            raise ValueError("RATE_LIMIT_PER_MINUTE must be >= 1")
        return self


settings = Settings().validate()
