"""Add rule_configs table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rule_configs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),   # DISABLED | OVERRIDE_SEVERITY
        sa.Column("severity", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "rule_id", name="uq_rule_configs_workspace_rule"),
    )
    op.create_index("ix_rule_configs_workspace_id", "rule_configs", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_rule_configs_workspace_id", table_name="rule_configs")
    op.drop_table("rule_configs")
