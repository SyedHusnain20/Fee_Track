from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central app config. All values are read from environment variables
    (or a .env file locally). See .env.example for the full list.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Core ---
    APP_NAME: str = "Raabta"
    ENVIRONMENT: str = "development"  # development | production
    SECRET_KEY: str

    # --- Database ---
    POSTGRES_USER: str = "raabta"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "raabta"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # --- Attendance defaults (overridden per-category via SystemSetting at runtime) ---
    DEFAULT_GRACE_MINUTES: int = 15

    # --- Academic year ---
    ACADEMIC_YEAR_RESET_MONTH: int = 4  # April, admin-changeable via SystemSetting

    # --- Backblaze B2 (year-end archive + nightly backups) ---
    B2_KEY_ID: str | None = None
    B2_APPLICATION_KEY: str | None = None
    B2_BUCKET_NAME: str | None = None


settings = Settings()
