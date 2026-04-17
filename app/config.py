from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    ENVIRONMENT: str = "development"

    # Database (Supabase PostgreSQL)
    # Pooler URL for IPv4 networks (dev), Direct URL for IPv6 networks (production)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/postgres"
    DATABASE_URL_DIRECT: str = ""

    # Auth / JWT
    SECRET_KEY: str = "qvicko-dev-secret-key-change-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"

    # Supabase Storage
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "qvicko"

    # Redis
    REDIS_URL: str = ""

    # Resend (email)
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "noreply@qvicko.se"
    RESEND_FROM_NAME: str = "Qvicko"
    RESEND_WEBHOOK_SECRET: str = ""
    RESEND_INBOUND_WEBHOOK_SECRET: str = ""

    # AI (for site generation)
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-haiku-4-5-20251001"  # cheap default for lead generation

    # Password Reset
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # Email Verification
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Frontend URL (for email links)
    FRONTEND_URL: str = "http://localhost:3000"

    # Email addresses
    EMAIL_WILLIAM: str = "william@qvicko.com"
    EMAIL_HELP: str = "help@qvicko.com"
    EMAIL_NOREPLY: str = "noreply@qvicko.com"

    # Cloudflare (for subdomain DNS management)
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ZONE_ID: str = ""
    BASE_DOMAIN: str = "qvicko.se"  # e.g. slug.qvicko.se

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001"

    @property
    def effective_database_url(self) -> str:
        """Use direct connection in production (IPv6/Railway/Vercel), pooler in dev (IPv4)."""
        if self.ENVIRONMENT == "production" and self.DATABASE_URL_DIRECT:
            return self.DATABASE_URL_DIRECT
        return self.DATABASE_URL

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def supabase_storage_url(self) -> str:
        return f"{self.SUPABASE_URL}/storage/v1"


settings = Settings()
