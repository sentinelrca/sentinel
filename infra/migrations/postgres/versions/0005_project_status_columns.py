"""Add status, trace_count, import_count to projects table.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-17
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "projects",
        sa.Column("trace_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "projects",
        sa.Column("import_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("projects", "import_count")
    op.drop_column("projects", "trace_count")
    op.drop_column("projects", "status")
