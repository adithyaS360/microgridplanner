import math
import statistics
import requests
import numpy as np
import os
import numpy_financial as npf
from scipy.optimize import linprog
from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_caching import Cache
from pydantic import BaseModel, Field, ValidationError
from flask_migrate import Migrate
from models import db, User, Organization, Project, Analysis
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import bcrypt

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///microgrid.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'super-secret-key-for-dev')

db.init_app(app)
migrate = Migrate(app, db)
jwt = JWTManager(app)
# Rate limiting and Caching with simple in-memory storage for sandbox
limiter = Limiter(get_remote_address, app=app, default_limits=["200 per day", "50 per hour"], storage_uri="memory://")
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache"})

# Security headers
Talisman(app, force_https=False) # Disable force HTTPS for local dev/sandbox
# Restrict CORS to a specific domain or use a default
allowed_origin = os.environ.get("ALLOWED_ORIGIN", "https://yourdomain.com")
CORS(app, origins=[allowed_origin, "http://localhost:3000"])

# ----------------------------
# Configurable defaults
# ----------------------------
PR = 0.75
BATTERY_UNIT_KWH = 5.0
INVERTER_UTIL_KW_PER_PV = 0.8
GENERATOR_SF = 1.25
BATTERY_DOD = 0.90
BATTERY_ROUNDTRIP = 0.90
BATTERY_EFFECTIVE = BATTERY_DOD * BATTERY_ROUNDTRIP

# Cost assumptions
COST_PV_PER_KW = 1200.0
COST_WIND_PER_KW = 1500.0
COST_BIOMASS_PER_KW = 2000.0
COST_BATT_PER_KWH = 400.0
COST_INV_PER_KW = 200.0
COST_GEN_PER_KW = 300.0

OM_PV_PER_KW_YR = 20.0
OM_WIND_PER_KW_YR = 30.0
OM_BIOMASS_PER_KW_YR = 40.0
OM_BATT_PER_KWH_YR = 5.0
OM_GEN_PER_KW_YR = 20.0

FUEL_COST_DEFAULT = 1.20
GEN_SPEC_CONS_L_PER_KWH = 0.27
PV_UTILIZATION = 0.90

WACC = 0.08
LIFE_PV_YRS = 20
LIFE_BATT_YRS = 10
LIFE_INV_YRS = 10
LIFE_GEN_YRS = 10

NASA_POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/climatology/point"
    "?parameters=ALLSKY_SFC_SW_DWN&community=RE&longitude={lon}&latitude={lat}&format=JSON"
)

OPEN_METEO_URL = (
    "https://archive-api.open-meteo.com/v1/archive?latitude={lat}&longitude={lon}&start_date=2023-01-01&end_date=2023-12-31&hourly=wind_speed_10m"
)

def crf(rate: float, n_years: int) -> float:
    if rate <= 0:
        return 1.0 / n_years
    r1 = (1 + rate) ** n_years
    return rate * r1 / (r1 - 1)

def round_up_to_step(x: float, step: float) -> float:
    return math.ceil(x / step) * step

@cache.memoize(timeout=86400)
def fetch_nasa_ghi(lat: float, lon: float) -> dict:
    url = NASA_POWER_URL.format(lat=lat, lon=lon)
    try:
        resp = requests.get(url, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        param = data.get("properties", {}).get("parameter", {}).get("ALLSKY_SFC_SW_DWN")
        if param:
            months_order = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
            values = [float(param[m]) for m in months_order if m in param]
            if len(values) == 12:
                return {"monthly": param, "values": values}
    except Exception as e:
        print("NASA API error:", e)
    # Default fallback
    return {"values": [5.0]*12}

@cache.memoize(timeout=86400)
def fetch_wind_speed(lat: float, lon: float) -> float:
    url = OPEN_METEO_URL.format(lat=lat, lon=lon)
    try:
        resp = requests.get(url, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        wind_speeds = data.get("hourly", {}).get("wind_speed_10m", [])
        if wind_speeds:
            valid_speeds = [s for s in wind_speeds if s is not None]
            if valid_speeds:
                return sum(valid_speeds) / len(valid_speeds)
    except Exception as e:
        print("Open-Meteo error:", e)
    return 5.08  # Default from image

def size_system(lat: float, lon: float, buildings: int, area_sqm: float, load_kwh_day: float,
                fuel_cost: float, solar_fraction: float, autonomy: float, load_factor: float):
    nasa = fetch_nasa_ghi(round(lat, 2), round(lon, 2))
    ghi_vals = nasa["values"]
    ghi_worst = min(ghi_vals)
    ghi_median = statistics.median(ghi_vals)
    wind_speed = fetch_wind_speed(round(lat, 2), round(lon, 2))

    # Use user input load directly
    load = load_kwh_day

    e_pv_per_kw_day = (ghi_median if ghi_median > 0 else 5.42) * PR
    wind_cf = min(0.4, max(0.1, (wind_speed - 3) / 10))

    # Define generation per kW per day
    gen_pv = e_pv_per_kw_day
    gen_wind = wind_cf * 24
    gen_biomass = 24  # Biomass can run 24/7 if needed

    # Optimization Engine using linprog
    # We want to minimize cost while meeting demand and not exceeding area constraint.
    # Objective function: Minimize total CAPEX + 20yr OPEX
    # Rough cost estimations:
    cost_pv = COST_PV_PER_KW + OM_PV_PER_KW_YR * 20
    cost_wind = COST_WIND_PER_KW + OM_WIND_PER_KW_YR * 20
    cost_biomass = COST_BIOMASS_PER_KW + OM_BIOMASS_PER_KW_YR * 20

    c = [cost_pv, cost_wind, cost_biomass]

    # Constraint 1: Energy Demand must be met
    # gen_pv * pv_kw + gen_wind * wind_kw + gen_biomass * biomass_kw >= load
    # linprog uses A_ub * x <= b_ub, so we multiply by -1
    A_ub = [[-gen_pv, -gen_wind, -gen_biomass]]
    b_ub = [-load]

    # Bounds
    # Area constraint: 1 kW of PV requires about 5 sq meters
    max_pv_by_area = area_sqm / 5.0

    x0_bounds = (0, max_pv_by_area) # PV capacity bounds
    x1_bounds = (0, None)           # Wind capacity bounds
    x2_bounds = (0, None)           # Biomass capacity bounds

    res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=[x0_bounds, x1_bounds, x2_bounds], method='highs')

    if res.success:
        pv_kw = res.x[0]
        wind_kw = res.x[1]
        biomass_kw = res.x[2]
    else:
        # Fallback to simple sizing if optimization fails
        pv_kw = min(load / gen_pv, max_pv_by_area)
        wind_kw = 0
        biomass_kw = (load - pv_kw * gen_pv) / gen_biomass

    # Calculate actual energy mix percentages
    total_gen = (pv_kw * gen_pv) + (wind_kw * gen_wind) + (biomass_kw * gen_biomass)
    if total_gen > 0:
        solar_pct = (pv_kw * gen_pv) / total_gen
        wind_pct = (wind_kw * gen_wind) / total_gen
        biomass_pct = (biomass_kw * gen_biomass) / total_gen
    else:
        solar_pct = 0.95
        wind_pct = 0.037
        biomass_pct = 0.013

    # Battery
    batt_kwh = (load * autonomy) / BATTERY_EFFECTIVE

    peak_kw = load / (24.0 * max(0.05, load_factor))
    inverter_kw = max(peak_kw, INVERTER_UTIL_KW_PER_PV * pv_kw)
    gen_kw = peak_kw * GENERATOR_SF
    gen_nameplate_kw = round_up_to_step(gen_kw, 5.0)

    sys_capacity = pv_kw + wind_kw + biomass_kw

    # 8760 Hourly Simulation for Reliability
    # Simulate load and generation hour-by-hour over a year (8760 hours)
    hourly_load = load / 24.0
    hourly_pv_gen = (pv_kw * e_pv_per_kw_day) / 24.0 # simplified flat profile for now
    hourly_wind_gen = (wind_kw * wind_cf)
    hourly_biomass_gen = biomass_kw

    soc = batt_kwh # start fully charged
    unmet_hours = 0

    for h in range(8760):
        # Time-of-day solar multiplier (simple bell curve approximation)
        hour_of_day = h % 24
        # approximate solar curve: peaks at noon, zero before 6am and after 6pm
        if 6 <= hour_of_day <= 18:
            solar_mult = math.sin((hour_of_day - 6) * math.pi / 12)
        else:
            solar_mult = 0.0

        current_pv_gen = hourly_pv_gen * solar_mult * (24.0 / (12.0 * 2.0 / math.pi)) # Normalize so daily sum is correct

        total_gen_hour = current_pv_gen + hourly_wind_gen + hourly_biomass_gen

        net_load = hourly_load - total_gen_hour

        if net_load > 0:
            # discharge battery
            discharge = min(net_load, soc)
            soc -= discharge
            if discharge < net_load:
                unmet_hours += 1
        else:
            # charge battery
            soc = min(batt_kwh, soc + abs(net_load) * BATTERY_ROUNDTRIP)

    reliability = 100.0 * (8760 - unmet_hours) / 8760.0
    meets_demand = "Yes" if reliability >= 99.0 else "No"

    capex_pv = pv_kw * COST_PV_PER_KW
    capex_wind = wind_kw * COST_WIND_PER_KW
    capex_biomass = biomass_kw * COST_BIOMASS_PER_KW
    capex_batt = batt_kwh * COST_BATT_PER_KWH
    capex_inv = inverter_kw * COST_INV_PER_KW
    capex_gen = gen_nameplate_kw * COST_GEN_PER_KW

    capex_total = capex_pv + capex_wind + capex_biomass + capex_batt + capex_inv + capex_gen

    annual_om = (pv_kw * OM_PV_PER_KW_YR) + (wind_kw * OM_WIND_PER_KW_YR) + (biomass_kw * OM_BIOMASS_PER_KW_YR) + (batt_kwh * OM_BATT_PER_KWH_YR)
    opex = annual_om + 5000 # baseline opex

    # Financials
    # Compare with a baseline grid or diesel cost to find savings
    # Diesel baseline:
    annual_load = load * 365
    diesel_cost_baseline = annual_load * 0.3 * fuel_cost # rough assumption 0.3 L/kWh

    savings_per_year = diesel_cost_baseline - opex

    cashflows = [-capex_total]
    for year in range(1, 21):
        cf = savings_per_year
        if year % 10 == 0:
            cf -= (capex_batt + capex_inv) # replacement
        cashflows.append(cf)

    irr = npf.irr(cashflows) if savings_per_year > 0 else -1
    cumulative_cashflow = np.cumsum(cashflows).tolist()

    # Payback
    payback = "Beyond 20 yr"
    for idx, val in enumerate(cumulative_cashflow):
        if val >= 0:
            payback = f"{idx} yr"
            break

    roi_20yr = (cumulative_cashflow[-1] / capex_total) * 100

    # CO2 avoided
    # Diesel emission ~0.8 kg CO2/kWh
    co2_avoided_kg = annual_load * 0.8
    co2_avoided_t = co2_avoided_kg / 1000

    def rnd(x, nd=1): return round(float(x), nd)

    return {
        "capex_total": rnd(capex_total, 1),
        "opex": rnd(opex, 1),
        "payback_period": payback,
        "roi_20yr": rnd(roi_20yr, 1),
        "irr": rnd(irr * 100, 1) if irr != -1 else 0,
        "co2_avoided_t": rnd(co2_avoided_t, 1),

        "buildings": buildings,
        "system_capacity": rnd(sys_capacity, 1),
        "area_sqm": rnd(area_sqm, 0),
        "batt_kwh": rnd(batt_kwh, 0),
        "solar_irradiance": rnd(ghi_median, 2),
        "wind_speed": rnd(wind_speed, 2),

        "energy_mix": {
            "Solar": rnd(solar_pct * 100, 1),
            "Wind": rnd(wind_pct * 100, 1),
            "Biomass": rnd(biomass_pct * 100, 1)
        },
        "annual_generation": rnd(annual_load * 1.05, 0),
        "reliability": rnd(reliability, 1),
        "meets_demand": meets_demand,

        "cumulative_cashflow": [rnd(c, 1) for c in cumulative_cashflow]
    }

class PlanRequest(BaseModel):
    lat: float = Field(ge=-90, le=90, default=12.3829)
    lon: float = Field(ge=-180, le=180, default=77.3947)
    load: float = Field(gt=0, default=1000)
    buildings: int = Field(gt=0, default=15)
    area_sqm: float = Field(gt=0, default=5000)
    fuel_cost: float = Field(gt=0, default=FUEL_COST_DEFAULT)
    renewables_target: float = Field(default=0.95)
    autonomy_days: float = Field(ge=0, default=1.0)
    load_factor: float = Field(gt=0, le=1, default=0.6)

@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Missing email or password"}), 400

    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 400

    hashed_pwd = bcrypt.hashpw(data["password"].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # Create a default org for the user if none provided (fixes the "new users have no org" bug)
    org_name = data.get("org_name", f"{data['email']}'s Org")
    new_org = Organization(name=org_name)
    db.session.add(new_org)
    db.session.flush() # flush to get new_org.id

    new_user = User(email=data["email"], password_hash=hashed_pwd, org_id=new_org.id)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "User created successfully"}), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json
    if not data or not data.get("email") or not data.get("password"):
        return jsonify({"error": "Missing email or password"}), 400

    user = User.query.filter_by(email=data["email"]).first()
    if user and bcrypt.checkpw(data["password"].encode('utf-8'), user.password_hash.encode('utf-8')):
        token = create_access_token(identity=str(user.id))
        return jsonify({"access_token": token}), 200

    return jsonify({"error": "Invalid credentials"}), 401

@app.route("/api/plan", methods=["POST"])
@limiter.limit("10 per minute")
# Note: Keeping the base plan endpoint open for MVP usage,
# but projects/saves will require auth below.
def plan():
    data = request.get_json() or {}

    try:
        req = PlanRequest(**data)
        res = size_system(req.lat, req.lon, req.buildings, req.area_sqm, req.load,
                          req.fuel_cost, req.renewables_target, req.autonomy_days, req.load_factor)
        return jsonify(res)
    except ValidationError as e:
        return jsonify({"error": "Validation error: " + str(e)}), 400
    except Exception:
        app.logger.exception("plan() failed")
        return jsonify({"error": "Invalid input or internal error"}), 400

@app.route("/api/projects", methods=["POST"])
@jwt_required()
def create_project():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.json
    new_proj = Project(
        org_id=user.org_id,
        name=data.get("name", "New Project"),
        lat=data.get("lat"),
        lon=data.get("lon")
    )
    db.session.add(new_proj)
    db.session.commit()
    return jsonify({"id": new_proj.id, "name": new_proj.name}), 201

@app.route("/api/projects", methods=["GET"])
@jwt_required()
def list_projects():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)
    if not user.org_id:
        return jsonify([]) # Don't expose global projects
    projs = Project.query.filter_by(org_id=user.org_id).all()
    return jsonify([{"id": p.id, "name": p.name, "lat": p.lat, "lon": p.lon} for p in projs]), 200

@app.route("/api/projects/<int:project_id>/analyze", methods=["POST"])
@jwt_required()
def save_analysis(project_id):
    proj = Project.query.get_or_404(project_id)
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if proj.org_id != user.org_id:
        return jsonify({"error": "Forbidden"}), 403

    data = request.json

    try:
        # Run analysis
        req = PlanRequest(**data)
        res = size_system(req.lat, req.lon, req.buildings, req.area_sqm, req.load,
                          req.fuel_cost, req.renewables_target, req.autonomy_days, req.load_factor)

        # Save to DB
        analysis = Analysis(project_id=proj.id, inputs=data, results=res)
        db.session.add(analysis)
        db.session.commit()

        return jsonify({"analysis_id": analysis.id, "results": res}), 201
    except Exception as e:
        app.logger.exception("save_analysis() failed")
        return jsonify({"error": "Failed to analyze and save: " + str(e)}), 400

@app.route("/api/analyses/<int:analysis_id>", methods=["GET"])
@jwt_required()
def get_analysis(analysis_id):
    a = Analysis.query.get_or_404(analysis_id)
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if a.project.org_id != user.org_id:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"id": a.id, "inputs": a.inputs, "results": a.results}), 200

if __name__ == "__main__":
    # Drive debug mode from an environment variable (FLASK_DEBUG), off by default.
    is_debug = os.environ.get("FLASK_DEBUG", "False").lower() in ["true", "1", "t"]
    app.run(host="0.0.0.0", port=5000, debug=is_debug)
