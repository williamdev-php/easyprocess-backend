"""Add tracking_events table for frontend analytics pixel.

Revision ID: 011_add_tracking_events
Revises: 010_add_smartlead
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

revision = "011_add_tracking_events"
down_revision = "010_add_smartlead"
branch_labels = None
depends_on = None

SCHEMA = "easyprocess"


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        f"WHERE table_schema='{SCHEMA}' AND table_name=:table"
    ), {"table": table})
    return result.fetchone() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "tracking_events"):
        op.create_table(
            "tracking_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("visitor_id", sa.String(64), nullable=False),
            sa.Column("session_id", sa.String(64), nullable=False),
            sa.Column("event_type", sa.String(50), nullable=False),
            sa.Column("page_path", sa.String(500), nullable=False, server_default="/"),
            sa.Column("referrer", sa.String(1000), nullable=True),
            sa.Column("utm_source", sa.String(255), nullable=True),
            sa.Column("utm_medium", sa.String(255), nullable=True),
            sa.Column("utm_campaign", sa.String(255), nullable=True),
            sa.Column("utm_content", sa.String(255), nullable=True),
            sa.Column("utm_term", sa.String(255), nullable=True),
            sa.Column(
                "user_id", sa.String(36),
                sa.ForeignKey(f"{SCHEMA}.users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("metadata", sa.JSON, nullable=True),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(500), nullable=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            schema=SCHEMA,
        )

    # Indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_visitor_id "
        f"ON {SCHEMA}.tracking_events (visitor_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_session_id "
        f"ON {SCHEMA}.tracking_events (session_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_event_type "
        f"ON {SCHEMA}.tracking_events (event_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_created_at "
        f"ON {SCHEMA}.tracking_events (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_user_id "
        f"ON {SCHEMA}.tracking_events (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_utm_source "
        f"ON {SCHEMA}.tracking_events (utm_source)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tracking_event_created "
        f"ON {SCHEMA}.tracking_events (event_type, created_at)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_event_created")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_utm_source")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_user_id")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_created_at")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_event_type")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_session_id")
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.idx_tracking_visitor_id")
    op.drop_table("tracking_events", schema=SCHEMA)
