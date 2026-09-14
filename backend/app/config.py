from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://user:password@localhost:5432/vasool"
    CORS_ORIGINS: str = "*"

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""

    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    GEMINI_MODEL: str = "gemini-3-flash-preview"
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    AGENT_TIMEOUT_SECONDS: float = 12.0

    MAX_AUTO_RETRY_AMOUNT_PAISE: int = 500_000
    MAX_RETRY_ATTEMPTS: int = 3
    MIN_CONFIDENCE_TO_AUTO_EXECUTE: float = 0.75
    KILL_SWITCH_ENGAGED: bool = False

    VASOOL_API_KEY: str = ""
    AUTO_PROCESS_ENABLED: bool = True
    AUTO_PROCESS_INTERVAL_SECONDS: int = 60
    RETRY_LATER_DELAY_MINUTES: int = 30

    @property
    def cors_origins(self) -> list[str]:
        """Return explicit CORS origins, or '*' for a public development demo."""
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
