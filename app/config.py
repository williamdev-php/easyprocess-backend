import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
    MASTER_SESSION_EXPIRE_DAYS: int = 90  # Long-lived master session for trusted devices
    TRUSTED_DEVICE_REFRESH_DAYS: int = 30  # Refresh token lifetime for trusted devices
    JWT_ALGORITHM: str = "HS256"

    # Supabase Storage
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "qvicko"

    # Redis
    REDIS_URL: str = ""  # Proxy URL for development (e.g. redis://nozomi.proxy.rlwy.net:56479)
    REDIS_INTERNAL_URL: str = ""  # Internal URL for production (e.g. redis://redis.railway.internal:6379)

    @property
    def effective_redis_url(self) -> str:
        """Always use proxy URL (REDIS_URL). Internal networking is not available."""
        return self.REDIS_URL

    # Resend (email)
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "noreply@qvicko.com"
    RESEND_FROM_NAME: str = "Qvicko"
    RESEND_WEBHOOK_SECRET: str = ""
    RESEND_INBOUND_WEBHOOK_SECRET: str = ""

    # AutoBlogger email sender
    AUTOBLOGGER_MAIL_FROM_EMAIL: str = "noreply@autoblogger.se"
    AUTOBLOGGER_MAIL_FROM_NAME: str = "AutoBlogger"

    # Feyra email sender
    FEYRA_MAIL_FROM_EMAIL: str = "noreply@feyra.se"
    FEYRA_MAIL_FROM_NAME: str = "Feyra"

    # AI (for site generation)
    ANTHROPIC_API_KEY: str = ""
    AI_MODEL: str = "claude-haiku-4-5-20251001"  # cheap default for lead generation

    # Google AI (Gemini + Imagen/Nano Banana)
    GOOGLE_AI_API_KEY: str = ""

    # Password Reset
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # Email Verification
    EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS: int = 24

    # Frontend URL (for email links)
    FRONTEND_URL: str = "http://localhost:3000"

    # AutoBlogger frontend URL
    AUTOBLOGGER_FRONTEND_URL: str = "http://localhost:3002"

    # Feyra frontend URL
    FEYRA_FRONTEND_URL: str = "http://localhost:3005"

    # Email addresses
    EMAIL_WILLIAM: str = "william@qvicko.com"
    EMAIL_HELP: str = "help@qvicko.com"
    EMAIL_NOREPLY: str = "noreply@qvicko.com"

    BASE_DOMAIN: str = "qvickosite.com"  # e.g. slug.qvickosite.com

    # Vercel (for custom domain management on viewer project)
    VERCEL_API_TOKEN: str = ""
    VERCEL_PROJECT_ID: str = ""  # The viewer project ID or name
    VERCEL_TEAM_ID: str = ""  # Optional, required for team-scoped projects

    # Domain sales markup (percentage added on top of Vercel's domain price)
    DOMAIN_MARKUP_PERCENT: int = 30  # 30% markup by default

    # Smartlead (cold outreach)
    SMARTLEAD_API_KEY: str = ""
    SMARTLEAD_DAILY_SEND_LIMIT: int = 50
    SMARTLEAD_WARMUP_ENABLED: bool = True

    # Google OAuth
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Apple Sign-In
    APPLE_CLIENT_ID: str = ""  # Your app's Bundle ID (e.g. com.qvicko.ios)

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID: str = ""  # Deprecated — use STRIPE_BASIC_PRICE_ID / STRIPE_PRO_PRICE_ID
    STRIPE_BASIC_PRICE_ID: str = ""
    STRIPE_PRO_PRICE_ID: str = ""

    # Stripe Connect (for marketplace payments)
    STRIPE_CONNECT_WEBHOOK_SECRET: str = ""
    PLATFORM_FEE_PERCENT: float = 0.2  # Platform fee percentage per transaction (0.2%)

    # AutoBlogger Stripe Plans (same Stripe account, different price IDs)
    STRIPE_AUTOBLOGGER_PRO_PRICE_ID: str = ""
    STRIPE_AUTOBLOGGER_BUSINESS_PRICE_ID: str = ""

    # Feyra encryption key (Fernet key for IMAP/SMTP password encryption)
    FEYRA_ENCRYPTION_KEY: str = ""

    # AutoBlogger encryption key (Fernet key for platform_config secrets: Shopify tokens, WP passwords)
    AUTOBLOGGER_ENCRYPTION_KEY: str = ""

    # Shopify OAuth
    SHOPIFY_API_KEY: str = ""
    SHOPIFY_API_SECRET: str = ""
    SHOPIFY_SCOPES: str = "write_content,read_content"  # For blog posts

    # Viewer
    VIEWER_URL: str = "http://localhost:3001"
    REVALIDATION_SECRET: str = ""

    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:3001,http://localhost:3002,http://localhost:3005"

    @property
    def effective_database_url(self) -> str:
        """Use direct connection in production (IPv6/Railway/Vercel), pooler in dev (IPv4)."""
        if self.ENVIRONMENT == "production" and self.DATABASE_URL_DIRECT:
            return self.DATABASE_URL_DIRECT
        return self.DATABASE_URL

    @property
    def allowed_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
        # Ensure product frontend URLs are always included in CORS origins
        for url in (self.FRONTEND_URL, self.AUTOBLOGGER_FRONTEND_URL, self.FEYRA_FRONTEND_URL):
            if url and url not in origins:
                origins.append(url)
        return origins

    @property
    def supabase_storage_url(self) -> str:
        return f"{self.SUPABASE_URL}/storage/v1"

    def validate_production_secrets(self) -> None:
        """Raise on startup if production is using insecure defaults."""
        if self.ENVIRONMENT != "production":
            return
        if self.SECRET_KEY == "qvicko-dev-secret-key-change-in-production":
            raise RuntimeError(
                "FATAL: Production is using the default SECRET_KEY. "
                "Set a strong, unique SECRET_KEY environment variable."
            )
        required = {
            "DATABASE_URL": self.DATABASE_URL,
            "RESEND_API_KEY": self.RESEND_API_KEY,
            "ANTHROPIC_API_KEY": self.ANTHROPIC_API_KEY,
            "STRIPE_SECRET_KEY": self.STRIPE_SECRET_KEY,
            "STRIPE_WEBHOOK_SECRET": self.STRIPE_WEBHOOK_SECRET,
            "SMARTLEAD_API_KEY": self.SMARTLEAD_API_KEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise RuntimeError(
                f"FATAL: Missing required env vars for production: {', '.join(missing)}"
            )

        # AutoBlogger-specific production requirements
        ab_required = {
            "AUTOBLOGGER_ENCRYPTION_KEY": self.AUTOBLOGGER_ENCRYPTION_KEY,
            "STRIPE_AUTOBLOGGER_PRO_PRICE_ID": self.STRIPE_AUTOBLOGGER_PRO_PRICE_ID,
            "STRIPE_AUTOBLOGGER_BUSINESS_PRICE_ID": self.STRIPE_AUTOBLOGGER_BUSINESS_PRICE_ID,
        }
        ab_missing = [k for k, v in ab_required.items() if not v]
        if ab_missing:
            logger.warning(
                "AutoBlogger: missing recommended env vars for production: %s",
                ", ".join(ab_missing),
            )


settings = Settings()
settings.validate_production_secrets()
