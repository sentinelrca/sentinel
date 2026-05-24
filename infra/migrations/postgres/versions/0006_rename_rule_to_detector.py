"""Rename rule_configs → detector_configs and rule_id → detector_id throughout.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("rule_configs", "detector_configs")
    op.alter_column("detector_configs", "rule_id", new_column_name="detector_id")
    op.alter_column("insights", "rule_id", new_column_name="detector_id")


def downgrade() -> None:
    op.alter_column("insights", "detector_id", new_column_name="rule_id")
    op.alter_column("detector_configs", "detector_id", new_column_name="rule_id")
    op.rename_table("detector_configs", "rule_configs")
