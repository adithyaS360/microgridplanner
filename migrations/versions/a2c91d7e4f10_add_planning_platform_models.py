"""add planning platform models

Revision ID: a2c91d7e4f10
Revises: 711f39427b2a
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa

revision = "a2c91d7e4f10"
down_revision = "711f39427b2a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organization", sa.Column("brand_name", sa.String(length=255), nullable=True))
    op.add_column("organization", sa.Column("logo_url", sa.String(length=2048), nullable=True))
    op.add_column("organization", sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True))
    op.add_column("user", sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True))
    op.add_column("project", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("project", sa.Column("assumptions", sa.JSON(), nullable=True))
    op.add_column("project", sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True))
    op.add_column("analysis", sa.Column("name", sa.String(length=255), server_default="Base case", nullable=True))
    op.create_table("load_profile",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False), sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False), sa.Column("annual_kwh", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
    )
    op.create_table("tariff",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False), sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("energy_rate", sa.Float(), nullable=False), sa.Column("demand_rate", sa.Float(), nullable=False), sa.Column("fixed_monthly_charge", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
    )
    op.create_table("incentive",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("region", sa.String(length=255), nullable=False), sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("technology", sa.String(length=50), nullable=False), sa.Column("incentive_type", sa.String(length=30), nullable=False), sa.Column("value", sa.Float(), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("starts_on", sa.Date(), nullable=True), sa.Column("ends_on", sa.Date(), nullable=True),
    )
    op.create_table("equipment",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("org_id", sa.Integer(), nullable=False), sa.Column("category", sa.String(length=50), nullable=False), sa.Column("manufacturer", sa.String(length=255), nullable=False), sa.Column("model", sa.String(length=255), nullable=False), sa.Column("capacity_kw", sa.Float(), nullable=False), sa.Column("unit_cost", sa.Float(), nullable=False), sa.Column("metadata_json", sa.JSON(), nullable=False), sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
    )
    op.create_table("financial_scenario",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("project_id", sa.Integer(), nullable=False), sa.Column("name", sa.String(length=255), nullable=False), sa.Column("debt_ratio", sa.Float(), nullable=False), sa.Column("interest_rate", sa.Float(), nullable=False), sa.Column("term_years", sa.Integer(), nullable=False), sa.Column("tax_rate", sa.Float(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
    )
    op.create_table("api_key",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("org_id", sa.Integer(), nullable=False), sa.Column("name", sa.String(length=255), nullable=False), sa.Column("key_prefix", sa.String(length=16), nullable=False), sa.Column("key_hash", sa.String(length=255), nullable=False, unique=True), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False), sa.Column("last_used_at", sa.DateTime(), nullable=True), sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
    )
    for table, column in [("load_profile", "project_id"), ("tariff", "org_id"), ("incentive", "region"), ("equipment", "org_id"), ("financial_scenario", "project_id"), ("api_key", "org_id")]:
        op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    for table, column in [("api_key", "org_id"), ("financial_scenario", "project_id"), ("equipment", "org_id"), ("incentive", "region"), ("tariff", "org_id"), ("load_profile", "project_id")]:
        op.drop_index(f"ix_{table}_{column}", table_name=table)
    for table in ["api_key", "financial_scenario", "equipment", "incentive", "tariff", "load_profile"]:
        op.drop_table(table)
    op.drop_column("analysis", "name")
    op.drop_column("project", "updated_at")
    op.drop_column("project", "assumptions")
    op.drop_column("project", "description")
    op.drop_column("user", "created_at")
    op.drop_column("organization", "created_at")
    op.drop_column("organization", "logo_url")
    op.drop_column("organization", "brand_name")
