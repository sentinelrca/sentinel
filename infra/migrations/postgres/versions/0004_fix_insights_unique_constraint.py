"""Replace uq_insights_trace_rule with two partial unique indexes for project scoping.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-17
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing full unique constraint (it's a named constraint, not just an index)
    op.drop_constraint("uq_insights_trace_rule", "insights", type_="unique")

    # Partial unique index for continuous-sync insights (project_id IS NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_insights_trace_rule_sync "
        "ON insights (workspace_id, trace_id, rule_id) "
        "WHERE project_id IS NULL"
    )

    # Partial unique index for project-scoped insights (project_id IS NOT NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_insights_trace_rule_project "
        "ON insights (workspace_id, trace_id, rule_id, project_id) "
        "WHERE project_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_insights_trace_rule_sync")
    op.execute("DROP INDEX IF EXISTS uq_insights_trace_rule_project")
    op.create_unique_constraint(
        "uq_insights_trace_rule", "insights", ["workspace_id", "trace_id", "rule_id"]
    )
