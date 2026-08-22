from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://user:password@localhost:5432/vasool"

    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""

    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""

    MAX_AUTO_RETRY_AMOUNT_PAISE: int = 500_000  # ₹5,000 ceiling for auto-execute
    MAX_RETRY_ATTEMPTS: int = 3
    MIN_CONFIDENCE_TO_AUTO_EXECUTE: float = 0.75


settings = Settings()