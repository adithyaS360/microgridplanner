from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

db = SQLAlchemy()


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    brand_name = db.Column(db.String(255))
    logo_url = db.Column(db.String(2048))
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)

    users = db.relationship("User", backref="organization", lazy=True)
    projects = db.relationship("Project", backref="organization", lazy=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default="member")
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    lat = db.Column(db.Float, nullable=False)
    lon = db.Column(db.Float, nullable=False)
    assumptions = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    analyses = db.relationship("Analysis", backref="project", lazy=True, cascade="all, delete-orphan")
    load_profiles = db.relationship("LoadProfile", backref="project", lazy=True, cascade="all, delete-orphan")


class Analysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False, default="Base case")
    inputs = db.Column(db.JSON, nullable=False)
    results = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)


class LoadProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    interval_minutes = db.Column(db.Integer, nullable=False, default=60)
    values = db.Column(db.JSON, nullable=False)
    annual_kwh = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)


class Tariff(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    currency = db.Column(db.String(8), nullable=False, default="USD")
    energy_rate = db.Column(db.Float, nullable=False)
    demand_rate = db.Column(db.Float, nullable=False, default=0)
    fixed_monthly_charge = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)


class Incentive(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    region = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    technology = db.Column(db.String(50), nullable=False, default="solar")
    incentive_type = db.Column(db.String(30), nullable=False, default="percent_capex")
    value = db.Column(db.Float, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    starts_on = db.Column(db.Date)
    ends_on = db.Column(db.Date)


class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)
    manufacturer = db.Column(db.String(255), nullable=False)
    model = db.Column(db.String(255), nullable=False)
    capacity_kw = db.Column(db.Float, nullable=False)
    unit_cost = db.Column(db.Float, nullable=False)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)


class FinancialScenario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    debt_ratio = db.Column(db.Float, nullable=False, default=0)
    interest_rate = db.Column(db.Float, nullable=False, default=0)
    term_years = db.Column(db.Integer, nullable=False, default=10)
    tax_rate = db.Column(db.Float, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)


class ApiKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    key_prefix = db.Column(db.String(16), nullable=False)
    key_hash = db.Column(db.String(255), nullable=False, unique=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    last_used_at = db.Column(db.DateTime)
