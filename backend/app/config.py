"""
Configuration module for AmpelBot backend.
Loads environment variables and resolves runtime service credentials.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
env_path = BASE_DIR / ".env"
load_dotenv(dotenv_path=env_path if env_path.exists() else None)


class Settings:
    PAYPAL_CLIENT_ID: str = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    PAYPAL_CLIENT_SECRET: str = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    PAYPAL_BASE_URL: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8001"))

    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    OPENAI_COMPAT_API_KEY: str = os.getenv("OPENAI_COMPAT_API_KEY", "").strip()
    OPENAI_COMPAT_BASE_URL: str = os.getenv("OPENAI_COMPAT_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    OPENAI_COMPAT_MODEL: str = os.getenv("OPENAI_COMPAT_MODEL", "google/gemini-2.5-flash").strip()

    DEAL_SIGNING_SECRET: str = os.getenv("DEAL_SIGNING_SECRET", "ampelbot-secret-deal-signing-key-hackathon-2026").strip()
    REQUIRE_DEAL_LOCK: bool = os.getenv("REQUIRE_DEAL_LOCK", "false").strip().lower() in ("true", "1", "yes")

    @property
    def is_paypal_configured(self) -> bool:
        return bool(
            self.PAYPAL_CLIENT_ID
            and self.PAYPAL_CLIENT_SECRET
            and "your_paypal_sandbox_client_id_here" not in self.PAYPAL_CLIENT_ID
            and "your_paypal_sandbox_client_secret_here" not in self.PAYPAL_CLIENT_SECRET
        )

    @property
    def is_gemini_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY and "your_" not in self.GEMINI_API_KEY)

    @property
    def is_openai_compat_configured(self) -> bool:
        return bool(self.OPENAI_COMPAT_API_KEY and "your_" not in self.OPENAI_COMPAT_API_KEY)


settings = Settings()
