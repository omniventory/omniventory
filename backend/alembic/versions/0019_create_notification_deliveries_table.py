"""Create notification_deliveries table.

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-20 00:00:00.000000 UTC

M4 Step 7 — delivery log for external notification channels.

``notification_deliveries`` records each attempt by an external channel (email,
http, mqtt) to deliver a notification row.  It is:
- Written by channel adapters (EmailChannel, HttpChannel, MqttChannel) in
  Phase C steps (7-9).
- Used for **idempotency**: a channel skips any notification that already has a
  ``status='sent'`` row for that channel; a ``'failed'`` row may be retried.
- Cascades on parent deletion (``ondelete=CASCADE``): removing a notification
  removes its delivery log.

See M4.md §3.6 for the full schema rationale.

Migration is fully reversible: upgrade creates the table + index, downgrade
drops the table.
"""

import sqlalchemy as sa

from alembic import op

# Revision identifiers used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    """Create the notification_deliveries table with indexes."""
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "notification_id",
            sa.Integer(),
            sa.ForeignKey(
                "notifications.id",
                name="fk_notification_deliveries_notification_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Index on (notification_id, channel) for idempotency lookups.
    op.create_index(
        "ix_notification_deliveries_notification_channel",
        "notification_deliveries",
        ["notification_id", "channel"],
        unique=False,
    )


def downgrade() -> None:
    """Drop the notification_deliveries table and its indexes."""
    op.drop_index(
        "ix_notification_deliveries_notification_channel",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_deliveries")
