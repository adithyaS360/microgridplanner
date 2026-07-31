import csv
import hashlib
import io
import math
import os
import secrets
import statistics
from datetime import date

import bcrypt
import numpy as np
import numpy_financial as npf
import requests
from flask import Flask, jsonify, request, send_file
from flask_caching import Cache
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_talisman import Talisman
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from scipy.optimize import linprog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import func

from models import Analysis, ApiKey, Equipment, FinancialScenario, Incentive, LoadProfile, Organization, Project, Tariff, User, db

app = Flask(__name__)
app.config.update(
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:///microgrid.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY") or secrets.token_urlsafe(48),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)
db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300})
Talisman(app, force_https=os.environ.get("FORCE_HTTPS", "false").lower() == "true")
CORS(app, origins=[origin.strip() for origin in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",")])

NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=ALLSKY_SFC_SW_DWN&community=RE&longitude={lon}&latitude={lat}&format=JSON"
OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2023-01-01&end_date=2023-12-31&hourly=wind_speed_10m"

DEFAULT_ASSUMPTIONS = {
    "pv_cost_per_kw": 1200.0, "wind_cost_per_kw": 1500.0, "biomass_cost_per_kw": 2000.0,
    "battery_cost_per_kwh": 400.0, "inverter_cost_per_kw": 200.0, "generator_cost_per_kw": 300.0,
    "fuel_cost": 1.20, "discount_rate": 0.08, "project_life_years": 20,
    "battery_dod": 0.90, "battery_roundtrip_efficiency": 0.90, "performance_ratio": 0.75,
}


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def finite(value):
    try:
        if not math.isfinite(float(value)):
            raise ValueError("must be finite")
    except (TypeError, ValueError):
        if isinstance(value, str):
            return value
        raise
    return value


class PlanRequest(RequestModel):
    lat: float = Field(ge=-90, le=90, default=12.3829)
    lon: float = Field(ge=-180, le=180, default=77.3947)
    load: float = Field(gt=0, default=1000)
    buildings: int = Field(gt=0, default=15)
    area_sqm: float = Field(gt=0, default=5000)
    fuel_cost: float = Field(gt=0, default=1.2)
    renewables_target: float = Field(ge=0, le=1, default=0.95)
    autonomy_days: float = Field(ge=0, le=7, default=1.0)
    load_factor: float = Field(gt=0, le=1, default=0.6)
    weather_case: str = Field(pattern="^(P50|P90)$", default="P50")
    assumptions: dict[str, float] = Field(default_factory=dict)
    load_profile_id: int | None = None

    @field_validator("lat", "lon", "load", "area_sqm", "fuel_cost", "renewables_target", "autonomy_days", "load_factor", mode="before")
    @classmethod
    def check_finite(cls, value):
        return finite(value)


class ProjectRequest(RequestModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    assumptions: dict[str, float] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class RoleRequest(RequestModel):
    role: str = Field(pattern="^(admin|member|viewer)$")


class TariffRequest(RequestModel):
    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(default="USD", min_length=3, max_length=8)
    energy_rate: float = Field(ge=0)
    demand_rate: float = Field(ge=0, default=0)
    fixed_monthly_charge: float = Field(ge=0, default=0)


class IncentiveRequest(RequestModel):
    region: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    technology: str = Field(default="solar", max_length=50)
    incentive_type: str = Field(default="percent_capex", pattern="^(percent_capex|per_kw|fixed)$")
    value: float = Field(ge=0)


class FinanceRequest(RequestModel):
    name: str = Field(default="Base financing", min_length=1, max_length=255)
    debt_ratio: float = Field(ge=0, le=1, default=0)
    interest_rate: float = Field(ge=0, le=1, default=0)
    term_years: int = Field(ge=1, le=40, default=10)
    tax_rate: float = Field(ge=0, le=1, default=0)


class EquipmentRequest(RequestModel):
    category: str = Field(pattern="^(pv|wind|biomass|inverter|generator|battery)$")
    manufacturer: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    capacity_kw: float = Field(gt=0)
    unit_cost: float = Field(ge=0)
    metadata_json: dict = Field(default_factory=dict)


class BrandRequest(RequestModel):
    brand_name: str = Field(default="", max_length=255)
    logo_url: str = Field(default="", max_length=2048)


def json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def validate(model, payload):
    try:
        return model(**payload), None
    except ValidationError as exc:
        return None, (jsonify({"error": "Validation error", "details": exc.errors()}), 400)


def current_user():
    identity = get_jwt_identity()
    return db.session.get(User, int(identity)) if identity else None


def require_role(*roles):
    def decorator(fn):
        @jwt_required()
        def wrapped(*args, **kwargs):
            user = current_user()
            if not user or user.role not in roles:
                return jsonify({"error": "Insufficient permissions"}), 403
            return fn(*args, **kwargs)
        wrapped.__name__ = fn.__name__
        return wrapped
    return decorator


def project_for_user(project_id, user):
    project = db.session.get(Project, project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if not user or project.org_id != user.org_id:
        return None, (jsonify({"error": "Forbidden"}), 403)
    return project, None


def merged_assumptions(overrides=None):
    values = DEFAULT_ASSUMPTIONS.copy()
    for key, value in (overrides or {}).items():
        if key not in values or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid assumption: {key}")
        values[key] = float(value)
    if not 0 < values["battery_dod"] <= 1 or not 0 < values["battery_roundtrip_efficiency"] <= 1 or not 0 < values["performance_ratio"] <= 1:
        raise ValueError("Battery and performance assumptions must be between 0 and 1")
    return values


@cache.memoize(timeout=86400)
def fetch_nasa_ghi(lat, lon):
    try:
        response = requests.get(NASA_POWER_URL.format(lat=lat, lon=lon), timeout=12)
        response.raise_for_status()
        monthly = response.json().get("properties", {}).get("parameter", {}).get("ALLSKY_SFC_SW_DWN", {})
        months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
        values = [float(monthly[month]) for month in months]
        if len(values) == 12:
            return values
    except (requests.RequestException, TypeError, ValueError, KeyError):
        app.logger.warning("NASA weather lookup failed; using fallback")
    return [5.0] * 12


@cache.memoize(timeout=86400)
def fetch_wind_speed(lat, lon):
    try:
        response = requests.get(OPEN_METEO_URL.format(lat=lat, lon=lon), timeout=12)
        response.raise_for_status()
        values = [v for v in response.json().get("hourly", {}).get("wind_speed_10m", []) if v is not None]
        if values:
            return float(statistics.fmean(values))
    except (requests.RequestException, TypeError, ValueError):
        app.logger.warning("Open-Meteo lookup failed; using fallback")
    return 5.08


def hourly_profile(values, fallback_daily):
    if not values:
        return [fallback_daily / 24] * 8760
    if len(values) == 24:
        return values * 365
    if len(values) == 8760:
        return values
    raise ValueError("Load profile must contain exactly 24 or 8760 hourly kWh values")


def size_system(plan, profile_values=None):
    assumptions = merged_assumptions(plan.assumptions)
    weather_factor = 0.85 if plan.weather_case == "P90" else 1.0
    ghi_median = statistics.median(fetch_nasa_ghi(round(plan.lat, 2), round(plan.lon, 2))) * weather_factor
    wind_speed = fetch_wind_speed(round(plan.lat, 2), round(plan.lon, 2)) * weather_factor
    hourly_loads = hourly_profile(profile_values, plan.load)
    annual_load = sum(hourly_loads)
    load = annual_load / 365
    pv_kwh_per_kw_day = max(0.1, ghi_median * assumptions["performance_ratio"])
    wind_cf = min(0.4, max(0.1, (wind_speed - 3) / 10))
    daily_generation = [pv_kwh_per_kw_day, wind_cf * 24, 24]
    capital_costs = [
        assumptions["pv_cost_per_kw"] + 20 * 20,
        assumptions["wind_cost_per_kw"] + 30 * 20,
        assumptions["biomass_cost_per_kw"] + 40 * 20,
    ]
    max_pv = plan.area_sqm / 5
    result = linprog(
        capital_costs,
        A_ub=[[-daily_generation[0], -daily_generation[1], -daily_generation[2]], [-daily_generation[0], -daily_generation[1], 0]],
        b_ub=[-load, -(plan.renewables_target * load)],
        bounds=[(0, max_pv), (0, None), (0, None)], method="highs",
    )
    if not result.success:
        raise ValueError("Unable to find a feasible system design")
    pv_kw, wind_kw, biomass_kw = result.x
    battery_kwh = load * plan.autonomy_days / (assumptions["battery_dod"] * assumptions["battery_roundtrip_efficiency"])
    peak_kw = max(hourly_loads) if profile_values else load / (24 * max(0.05, plan.load_factor))
    inverter_kw = max(peak_kw, 0.8 * pv_kw)
    generator_kw = math.ceil((peak_kw * 1.25) / 5) * 5
    soc, unmet_hours = battery_kwh, 0
    for hour, hour_load in enumerate(hourly_loads):
        hour_of_day = hour % 24
        solar_shape = math.sin((hour_of_day - 6) * math.pi / 12) if 6 <= hour_of_day <= 18 else 0
        pv_output = (pv_kw * pv_kwh_per_kw_day / 24) * solar_shape * math.pi
        generated = pv_output + wind_kw * wind_cf + biomass_kw
        net = hour_load - generated
        if net > 0:
            discharge = min(net, soc)
            soc -= discharge
            unmet_hours += int(discharge + 1e-9 < net)
        else:
            soc = min(battery_kwh, soc + (-net) * assumptions["battery_roundtrip_efficiency"])
    total_daily_generation = sum(capacity * generation for capacity, generation in zip([pv_kw, wind_kw, biomass_kw], daily_generation))
    capex = pv_kw * assumptions["pv_cost_per_kw"] + wind_kw * assumptions["wind_cost_per_kw"] + biomass_kw * assumptions["biomass_cost_per_kw"] + battery_kwh * assumptions["battery_cost_per_kwh"] + inverter_kw * assumptions["inverter_cost_per_kw"] + generator_kw * assumptions["generator_cost_per_kw"]
    annual_om = pv_kw * 20 + wind_kw * 30 + biomass_kw * 40 + battery_kwh * 5 + generator_kw * 20 + 5000
    diesel_baseline = annual_load * 0.3 * plan.fuel_cost
    savings = diesel_baseline - annual_om
    project_life_years = int(assumptions["project_life_years"])
    cashflows = [-capex] + [savings - ((battery_kwh * assumptions["battery_cost_per_kwh"] + inverter_kw * assumptions["inverter_cost_per_kw"]) if year % 10 == 0 else 0) for year in range(1, project_life_years + 1)]
    cumulative = np.cumsum(cashflows).tolist()
    irr = npf.irr(cashflows) if savings > 0 else float("nan")
    proportions = np.array([pv_kw * daily_generation[0], wind_kw * daily_generation[1], biomass_kw * daily_generation[2]]) / total_daily_generation
    payback = next((f"{year} yr" for year, value in enumerate(cumulative) if value >= 0), "Beyond project life")
    return {
        "capex_total": round(float(capex), 1), "opex": round(float(annual_om), 1), "payback_period": payback,
        "roi_20yr": round(float(cumulative[-1] / capex * 100), 1), "irr": round(float(irr * 100), 1) if np.isfinite(irr) else 0,
        "co2_avoided_t": round(float(annual_load * 0.8 / 1000), 1), "buildings": plan.buildings,
        "system_capacity": round(float(pv_kw + wind_kw + biomass_kw), 1), "area_sqm": round(plan.area_sqm),
        "batt_kwh": round(float(battery_kwh)), "solar_irradiance": round(float(ghi_median), 2), "wind_speed": round(float(wind_speed), 2),
        "energy_mix": {"Solar": round(float(proportions[0] * 100), 1), "Wind": round(float(proportions[1] * 100), 1), "Biomass": round(float(proportions[2] * 100), 1)},
        "annual_generation": round(float(total_daily_generation * 365)), "annual_load": round(float(annual_load)),
        "reliability": round(100 * (8760 - unmet_hours) / 8760, 2), "meets_demand": "Yes" if unmet_hours <= 87 else "No",
        "weather_case": plan.weather_case, "assumptions": assumptions, "cumulative_cashflow": [round(float(value), 1) for value in cumulative],
        "component_capacities": {"pv_kw": round(float(pv_kw), 2), "wind_kw": round(float(wind_kw), 2), "biomass_kw": round(float(biomass_kw), 2), "inverter_kw": round(float(inverter_kw), 2), "generator_kw": round(float(generator_kw), 2)},
    }


def serialize_project(project):
    return {"id": project.id, "name": project.name, "description": project.description, "lat": project.lat, "lon": project.lon, "assumptions": project.assumptions, "created_at": project.created_at.isoformat()}


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "Upload exceeds the 2 MB limit"}), 413


@app.route("/api/health")
@limiter.exempt
def health():
    return jsonify({"status": "ok"})


@app.route("/api/auth/register", methods=["POST"])
@limiter.limit("5 per minute")
def register():
    data = json_object()
    if not data or not isinstance(data.get("email"), str) or not isinstance(data.get("password"), str):
        return jsonify({"error": "Email and password are required"}), 400
    email, password = data["email"].strip().lower(), data["password"]
    if len(email) > 255 or "@" not in email or len(password) < 8:
        return jsonify({"error": "Use a valid email and a password of at least 8 characters"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400
    org = Organization(name=data.get("organization_name", f"{email}'s organization")[:255])
    user = User(email=email, password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(), organization=org, role="admin")
    try:
        db.session.add(user); db.session.commit()
    except IntegrityError:
        db.session.rollback(); return jsonify({"error": "Email already registered"}), 400
    return jsonify({"message": "User created", "organization_id": org.id}), 201


@app.route("/api/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def login():
    data = json_object() or {}
    if not isinstance(data.get("email"), str) or not isinstance(data.get("password"), str):
        return jsonify({"error": "Email and password are required"}), 400
    user = User.query.filter_by(email=data["email"].strip().lower()).first()
    if not user or not bcrypt.checkpw(data["password"].encode(), user.password_hash.encode()):
        return jsonify({"error": "Invalid credentials"}), 401
    return jsonify({"access_token": create_access_token(identity=str(user.id)), "user": {"id": user.id, "email": user.email, "role": user.role, "organization": user.organization.name}})


@app.route("/api/plan", methods=["POST"])
@limiter.limit("10 per minute")
def plan():
    payload = json_object()
    if payload is None: return jsonify({"error": "Request body must be a JSON object"}), 400
    plan_request, error = validate(PlanRequest, payload)
    if error: return error
    try:
        return jsonify(size_system(plan_request))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/v1/plan", methods=["POST"])
@limiter.limit("30 per minute")
def white_label_plan():
    raw_key = request.headers.get("X-API-Key", "")
    if not raw_key.startswith("mgp_"):
        return jsonify({"error": "A valid X-API-Key is required"}), 401
    api_key = ApiKey.query.filter_by(key_hash=hashlib.sha256(raw_key.encode()).hexdigest(), active=True).first()
    if not api_key:
        return jsonify({"error": "A valid X-API-Key is required"}), 401
    payload = json_object()
    plan_request, error = validate(PlanRequest, payload or {})
    if error: return error
    try:
        result = size_system(plan_request)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    api_key.last_used_at = func.now(); db.session.commit()
    organization = db.session.get(Organization, api_key.org_id)
    return jsonify({"brand": {"name": organization.brand_name or organization.name, "logo_url": organization.logo_url}, "result": result})


@app.route("/api/projects", methods=["GET", "POST"])
@jwt_required()
def projects():
    user = current_user()
    if request.method == "GET":
        return jsonify([serialize_project(project) for project in Project.query.filter_by(org_id=user.org_id).order_by(Project.updated_at.desc()).all()])
    payload = json_object()
    project_request, error = validate(ProjectRequest, payload or {})
    if error: return error
    try: assumptions = merged_assumptions(project_request.assumptions)
    except ValueError as exc: return jsonify({"error": str(exc)}), 400
    project = Project(org_id=user.org_id, name=project_request.name, description=project_request.description, lat=project_request.lat, lon=project_request.lon, assumptions=assumptions)
    db.session.add(project); db.session.commit()
    return jsonify(serialize_project(project)), 201


@app.route("/api/projects/<int:project_id>", methods=["GET", "PATCH", "DELETE"])
@jwt_required()
def project_detail(project_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    if request.method == "GET": return jsonify(serialize_project(project))
    if request.method == "DELETE":
        db.session.delete(project); db.session.commit(); return "", 204
    payload = json_object(); project_request, validation_error = validate(ProjectRequest, payload or {})
    if validation_error: return validation_error
    try: assumptions = merged_assumptions(project_request.assumptions)
    except ValueError as exc: return jsonify({"error": str(exc)}), 400
    project.name, project.description, project.lat, project.lon, project.assumptions = project_request.name, project_request.description, project_request.lat, project_request.lon, assumptions
    db.session.commit(); return jsonify(serialize_project(project))


@app.route("/api/projects/<int:project_id>/analyze", methods=["POST"])
@jwt_required()
def save_analysis(project_id):
    user = current_user(); project, error = project_for_user(project_id, user)
    if error: return error
    payload = json_object() or {}
    payload["lat"], payload["lon"] = payload.get("lat", project.lat), payload.get("lon", project.lon)
    payload["assumptions"] = {**project.assumptions, **payload.get("assumptions", {})}
    plan_request, validation_error = validate(PlanRequest, payload)
    if validation_error: return validation_error
    profile_values = None
    if plan_request.load_profile_id:
        profile = db.session.get(LoadProfile, plan_request.load_profile_id)
        if not profile or profile.project_id != project.id: return jsonify({"error": "Load profile not found"}), 404
        profile_values = profile.values
    try: result = size_system(plan_request, profile_values)
    except ValueError as exc: return jsonify({"error": str(exc)}), 400
    analysis = Analysis(project_id=project.id, name=payload.get("name", "Base case")[:255], inputs=plan_request.model_dump(), results=result)
    db.session.add(analysis); db.session.commit()
    return jsonify({"analysis_id": analysis.id, "results": result}), 201


@app.route("/api/projects/<int:project_id>/analyses")
@jwt_required()
def analyses(project_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    return jsonify([{"id": analysis.id, "name": analysis.name, "created_at": analysis.created_at.isoformat(), "results": analysis.results} for analysis in Analysis.query.filter_by(project_id=project.id).order_by(Analysis.created_at.desc()).all()])


@app.route("/api/projects/<int:project_id>/load-profiles", methods=["GET", "POST"])
@jwt_required()
def load_profiles(project_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    if request.method == "GET": return jsonify([{"id": profile.id, "name": profile.name, "interval_minutes": profile.interval_minutes, "annual_kwh": profile.annual_kwh} for profile in project.load_profiles])
    raw = request.files.get("file")
    if not raw or not raw.filename.lower().endswith(".csv"): return jsonify({"error": "Upload a CSV containing one numeric kWh value per row"}), 400
    try:
        rows = list(csv.reader(io.StringIO(raw.stream.read().decode("utf-8-sig"))))
        values = [float(row[-1]) for row in rows if row and row[-1].strip() and row[-1].strip().lower() not in {"kwh", "load", "value"}]
        if len(values) not in {24, 8760} or any(value < 0 or not math.isfinite(value) for value in values): raise ValueError
    except (UnicodeDecodeError, ValueError, IndexError): return jsonify({"error": "CSV must have 24 or 8760 non-negative numeric rows"}), 400
    profile = LoadProfile(project_id=project.id, name=request.form.get("name", raw.filename)[:255], interval_minutes=60, values=values, annual_kwh=sum(values) * (365 if len(values) == 24 else 1))
    db.session.add(profile); db.session.commit()
    return jsonify({"id": profile.id, "annual_kwh": profile.annual_kwh}), 201


@app.route("/api/projects/<int:project_id>/sensitivity", methods=["POST"])
@jwt_required()
def sensitivity(project_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    payload = json_object() or {}
    variable = payload.pop("variable", "fuel_cost")
    values = payload.pop("values", [0.8, 1.0, 1.2, 1.5])
    base, validation_error = validate(PlanRequest, {**payload, "lat": payload.get("lat", project.lat), "lon": payload.get("lon", project.lon), "assumptions": {**project.assumptions, **payload.get("assumptions", {})}})
    if validation_error: return validation_error
    if variable not in {"fuel_cost", "renewables_target", "load"} or not isinstance(values, list) or len(values) > 25: return jsonify({"error": "Invalid sensitivity variable or values"}), 400
    scenarios = []
    for value in values:
        data = base.model_dump(); data[variable] = value
        scenario, scenario_error = validate(PlanRequest, data)
        if scenario_error: return scenario_error
        result = size_system(scenario); scenarios.append({"value": value, "capex_total": result["capex_total"], "irr": result["irr"], "payback_period": result["payback_period"]})
    return jsonify({"variable": variable, "scenarios": scenarios, "note": "For large Monte Carlo workloads, vectorize the hourly simulation with NumPy or compile it with Numba."})


@app.route("/api/portfolio")
@jwt_required()
def portfolio():
    user = current_user(); projects = Project.query.filter_by(org_id=user.org_id).all(); items = []
    for project in projects:
        analysis = Analysis.query.filter_by(project_id=project.id).order_by(Analysis.created_at.desc()).first()
        items.append({"project": serialize_project(project), "latest_analysis": analysis.results if analysis else None})
    return jsonify(items)


@app.route("/api/tariffs", methods=["GET", "POST"])
@jwt_required()
def tariffs():
    user = current_user()
    if request.method == "GET": return jsonify([{"id": tariff.id, "name": tariff.name, "currency": tariff.currency, "energy_rate": tariff.energy_rate, "demand_rate": tariff.demand_rate, "fixed_monthly_charge": tariff.fixed_monthly_charge} for tariff in Tariff.query.filter_by(org_id=user.org_id).all()])
    tariff_request, error = validate(TariffRequest, json_object() or {})
    if error: return error
    tariff = Tariff(org_id=user.org_id, **tariff_request.model_dump()); db.session.add(tariff); db.session.commit(); return jsonify({"id": tariff.id}), 201


@app.route("/api/incentives", methods=["GET", "POST"])
@jwt_required()
def incentives():
    if request.method == "GET":
        region = request.args.get("region"); query = Incentive.query.filter_by(active=True)
        if region: query = query.filter_by(region=region)
        return jsonify([{"id": incentive.id, "region": incentive.region, "name": incentive.name, "technology": incentive.technology, "incentive_type": incentive.incentive_type, "value": incentive.value} for incentive in query.all()])
    if current_user().role != "admin": return jsonify({"error": "Insufficient permissions"}), 403
    incentive_request, error = validate(IncentiveRequest, json_object() or {})
    if error: return error
    incentive = Incentive(**incentive_request.model_dump()); db.session.add(incentive); db.session.commit(); return jsonify({"id": incentive.id}), 201


@app.route("/api/projects/<int:project_id>/financing", methods=["GET", "POST"])
@jwt_required()
def financing(project_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    if request.method == "GET": return jsonify([{"id": scenario.id, "name": scenario.name, "debt_ratio": scenario.debt_ratio, "interest_rate": scenario.interest_rate, "term_years": scenario.term_years, "tax_rate": scenario.tax_rate} for scenario in FinancialScenario.query.filter_by(project_id=project.id).all()])
    finance_request, validation_error = validate(FinanceRequest, json_object() or {})
    if validation_error: return validation_error
    scenario = FinancialScenario(project_id=project.id, **finance_request.model_dump()); db.session.add(scenario); db.session.commit(); return jsonify({"id": scenario.id}), 201


@app.route("/api/projects/<int:project_id>/financing/<int:scenario_id>/summary")
@jwt_required()
def financing_summary(project_id, scenario_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    scenario = db.session.get(FinancialScenario, scenario_id)
    analysis_id = request.args.get("analysis_id", type=int)
    analysis = db.session.get(Analysis, analysis_id) if analysis_id else Analysis.query.filter_by(project_id=project.id).order_by(Analysis.created_at.desc()).first()
    if not scenario or scenario.project_id != project.id or not analysis: return jsonify({"error": "Scenario or analysis not found"}), 404
    principal = analysis.results["capex_total"] * scenario.debt_ratio
    payment = principal / scenario.term_years if scenario.interest_rate == 0 else principal * (scenario.interest_rate * (1 + scenario.interest_rate) ** scenario.term_years) / ((1 + scenario.interest_rate) ** scenario.term_years - 1)
    balance, schedule = principal, []
    for year in range(1, scenario.term_years + 1):
        interest = balance * scenario.interest_rate; principal_paid = min(balance, payment - interest); balance -= principal_paid
        schedule.append({"year": year, "payment": round(payment, 2), "interest": round(interest, 2), "principal": round(principal_paid, 2), "balance": round(max(0, balance), 2)})
    return jsonify({"debt_amount": round(principal, 2), "equity_amount": round(analysis.results["capex_total"] - principal, 2), "annual_debt_service": round(payment, 2), "schedule": schedule})


@app.route("/api/projects/<int:project_id>/bom/<int:analysis_id>")
@jwt_required()
def bom(project_id, analysis_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    analysis = db.session.get(Analysis, analysis_id)
    if not analysis or analysis.project_id != project.id: return jsonify({"error": "Analysis not found"}), 404
    capacities = analysis.results["component_capacities"]; mapping = {"pv": "pv_kw", "wind": "wind_kw", "biomass": "biomass_kw", "inverter": "inverter_kw", "generator": "generator_kw"}; lines = []
    for category, capacity_key in mapping.items():
        equipment = Equipment.query.filter_by(org_id=project.org_id, category=category).order_by(Equipment.unit_cost.asc()).first()
        capacity = capacities[capacity_key]
        if equipment:
            quantity = math.ceil(capacity / equipment.capacity_kw); lines.append({"category": category, "required_kw": capacity, "manufacturer": equipment.manufacturer, "model": equipment.model, "quantity": quantity, "unit_cost": equipment.unit_cost, "subtotal": round(quantity * equipment.unit_cost, 2)})
        else: lines.append({"category": category, "required_kw": capacity, "status": "No catalog match"})
    return jsonify({"analysis_id": analysis.id, "lines": lines})


@app.route("/api/equipment", methods=["GET", "POST"])
@jwt_required()
def equipment_catalog():
    user = current_user()
    if request.method == "GET":
        return jsonify([{"id": item.id, "category": item.category, "manufacturer": item.manufacturer, "model": item.model, "capacity_kw": item.capacity_kw, "unit_cost": item.unit_cost, "metadata": item.metadata_json} for item in Equipment.query.filter_by(org_id=user.org_id).order_by(Equipment.category, Equipment.unit_cost).all()])
    if user.role != "admin": return jsonify({"error": "Insufficient permissions"}), 403
    equipment_request, error = validate(EquipmentRequest, json_object() or {})
    if error: return error
    item = Equipment(org_id=user.org_id, **equipment_request.model_dump())
    db.session.add(item); db.session.commit(); return jsonify({"id": item.id}), 201


@app.route("/api/projects/<int:project_id>/report/<int:analysis_id>.pdf")
@jwt_required()
def report(project_id, analysis_id):
    project, error = project_for_user(project_id, current_user())
    if error: return error
    analysis = db.session.get(Analysis, analysis_id)
    if not analysis or analysis.project_id != project.id: return jsonify({"error": "Analysis not found"}), 404
    result = analysis.results; stream = io.BytesIO(); document = SimpleDocTemplate(stream, pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch)
    styles = getSampleStyleSheet(); story = [Paragraph("Microgrid Feasibility Report", styles["Title"]), Paragraph(project.name, styles["Heading2"]), Paragraph(f"Location: {project.lat:.4f}, {project.lon:.4f} | Weather case: {result['weather_case']}", styles["Normal"]), Spacer(1, 0.2 * inch)]
    rows = [["Metric", "Result"], ["Capital expenditure", f"${result['capex_total']:,.0f}"], ["Annual OPEX", f"${result['opex']:,.0f}"], ["Payback", result["payback_period"]], ["IRR", f"{result['irr']:.1f}%"], ["Reliability", f"{result['reliability']:.2f}%"], ["Battery storage", f"{result['batt_kwh']:,.0f} kWh"], ["Annual generation", f"{result['annual_generation']:,.0f} kWh"]]
    table = Table(rows, colWidths=[2.7 * inch, 3.4 * inch]); table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]), ("PADDING", (0, 0), (-1, -1), 8)])); story += [table, Spacer(1, 0.2 * inch), Paragraph("Energy mix", styles["Heading2"]), Paragraph(", ".join(f"{source}: {value}%" for source, value in result["energy_mix"].items()), styles["Normal"]), Spacer(1, 0.2 * inch), Paragraph("Assumptions", styles["Heading2"]), Paragraph("This feasibility output uses the saved scenario assumptions and is intended for preliminary planning.", styles["Normal"])]
    document.build(story); stream.seek(0)
    return send_file(stream, mimetype="application/pdf", as_attachment=True, download_name=f"microgrid-report-{project.id}-{analysis.id}.pdf")


@app.route("/api/organization", methods=["GET", "PATCH"])
@require_role("admin")
def organization_settings():
    organization = current_user().organization
    if request.method == "GET": return jsonify({"id": organization.id, "name": organization.name, "brand_name": organization.brand_name, "logo_url": organization.logo_url})
    brand_request, error = validate(BrandRequest, json_object() or {})
    if error: return error
    organization.brand_name = brand_request.brand_name or None; organization.logo_url = brand_request.logo_url or None
    db.session.commit(); return jsonify({"id": organization.id, "brand_name": organization.brand_name, "logo_url": organization.logo_url})


@app.route("/api/organization/users", methods=["GET"])
@require_role("admin")
def organization_users():
    user = current_user(); return jsonify([{"id": member.id, "email": member.email, "role": member.role} for member in User.query.filter_by(org_id=user.org_id).all()])


@app.route("/api/organization/users/<int:user_id>/role", methods=["PATCH"])
@require_role("admin")
def change_role(user_id):
    admin = current_user(); member = db.session.get(User, user_id)
    if not member or member.org_id != admin.org_id: return jsonify({"error": "User not found"}), 404
    role_request, error = validate(RoleRequest, json_object() or {})
    if error: return error
    member.role = role_request.role; db.session.commit(); return jsonify({"id": member.id, "role": member.role})


@app.route("/api/api-keys", methods=["GET", "POST"])
@require_role("admin")
def api_keys():
    user = current_user()
    if request.method == "GET": return jsonify([{"id": key.id, "name": key.name, "prefix": key.key_prefix, "active": key.active, "created_at": key.created_at.isoformat()} for key in ApiKey.query.filter_by(org_id=user.org_id).all()])
    data = json_object() or {}; name = data.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 255: return jsonify({"error": "A key name is required"}), 400
    secret = f"mgp_{secrets.token_urlsafe(32)}"; key = ApiKey(org_id=user.org_id, name=name.strip(), key_prefix=secret[:12], key_hash=hashlib.sha256(secret.encode()).hexdigest())
    db.session.add(key); db.session.commit(); return jsonify({"id": key.id, "api_key": secret, "warning": "Copy this API key now; it cannot be shown again."}), 201


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG", "false").lower() in {"1", "true"})
