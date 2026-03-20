"""Initial schema — orgs, api_keys, executions, audit_log.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Organisations
    op.create_table(
        "organisations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("plan", sa.String(50), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )

    # API Keys
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_org_id", "api_keys", ["org_id"])

    # Workflow Executions (durable audit trail)
    op.create_table(
        "workflow_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("org_id", sa.String(36), sa.ForeignKey("organisations.id"), nullable=False),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column("workflow_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="PENDING"),
        sa.Column("context", sa.Text),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_tokens", sa.Integer, server_default="0"),
        sa.Column("total_steps", sa.Integer, server_default="0"),
    )
    op.create_index("ix_wf_executions_org_status", "workflow_executions", ["org_id", "status"])
    op.create_index("ix_wf_executions_workflow", "workflow_executions", ["workflow_id"])

    # Step Executions
    op.create_table(
        "step_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36),
                  sa.ForeignKey("workflow_executions.id"), nullable=False),
        sa.Column("step_name", sa.String(255), nullable=False),
        sa.Column("agent_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("attempt", sa.Integer, server_default="1"),
        sa.Column("tokens_used", sa.Integer, server_default="0"),
        sa.Column("duration_ms", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_step_executions_exec", "step_executions", ["execution_id"])

    # Audit Log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, autoincrement=True, primary_key=True),
        sa.Column("org_id", sa.String(36), nullable=False),
        sa.Column("event", sa.String(255), nullable=False),
        sa.Column("resource_type", sa.String(100)),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("actor", sa.String(255)),
        sa.Column("metadata", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_org_event", "audit_log", ["org_id", "event"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("step_executions")
    op.drop_table("workflow_executions")
    op.drop_table("api_keys")
    op.drop_table("organisations")
