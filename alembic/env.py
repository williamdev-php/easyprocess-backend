import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import settings
from app.database import Base, SCHEMA

# Import all models so metadata is populated
from app.auth.models import User, Session, AuditLog, SocialAccount, PasswordResetToken, EmailVerificationToken, SettingsAuditLog  # noqa: F401
from app.sites.models import Lead, ScrapedData, GeneratedSite, OutreachEmail, InboundEmail  # noqa: F401
from app.smartlead.models import SmartleadCampaign, SmartleadEmailAccount  # noqa: F401
from app.feyra.models import FeyraBase, FEYRA_SCHEMA  # noqa: F401
from app.feyra.models import EmailAccount, WarmupSettings, WarmupEmail  # noqa: F401
from app.feyra.models import Lead as FeyraLead, CrawlJob, CrawlResult  # noqa: F401
from app.feyra.models import Campaign, CampaignStep, CampaignLead, SentEmail, GlobalSettings  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url with the value from settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
