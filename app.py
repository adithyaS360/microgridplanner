# app.py
# Minimal microgrid planner MVP: Flask web app
# Inputs: latitude, longitude, daily load (kWh/day), optional fuel cost
# Fetches NASA POWER monthly GHI, sizes PV, battery, generator, and estimates costs

import math
import statistics
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ----------------------------
# Configurable defaults
# ----------------------------
PR = 0.75  # PV performance ratio (temp, wiring, dust, inverter)
RENEWABLES_TARGETS = {"60%": 0.60, "80%": 0.80, "95%": 0.95}
AUTONOMY_OPTIONS = {"0.5 days": 0.5, "1 day": 1.0, "2 days": 2.0}
LOAD_TYPES = {
    "Village (LF 0.6)": 0.60,
    "Mine (LF 0.5)": 0.50,
    "Base (LF 0.5)": 0.50,
    "Clinic (LF 0.7)": 0.70,
}

# BoM mapping
PANEL_WATTS = 400  # W per module
BATTERY_UNIT_KWH = 5.0  # kWh per battery module
INVERTER_UTIL_KW_PER_PV = 0.8  # inverter kW at least this fraction of PV kW

# Sizing safety factors
GENERATOR_SF = 1.25

# Battery assumptions
BATTERY_DOD = 0.90
BATTERY_ROUNDTRIP = 0.90  # round-trip efficiency
BATTERY_EFFECTIVE = BATTERY_DOD * BATTERY_ROUNDTRIP  # 0.81

# Cost assumptions (very rough, remote-friendly)
COST_PV_PER_KW = 1200.0        # USD/kW installed
COST_BATT_PER_KWH = 400.0      # USD/kWh installed
COST_INV_PER_KW = 200.0        # USD/kW
COST_GEN_PER_KW = 300.0        # USD/kW

OM_PV_PER_KW_YR = 20.0         # USD/kW-yr
OM_BATT_PER_KWH_YR = 5.0       # USD/kWh-yr
OM_GEN_PER_KW_YR = 20.0        # USD/kW-yr

FUEL_COST_DEFAULT = 1.20       # USD/L
GEN_SPEC_CONS_L_PER_KWH = 0.27 # L/kWh at ~70–80% load
PV_UTILIZATION = 0.90          # fraction of PV energy actually serving load

# Financial assumptions for LCOE
WACC = 0.08
LIFE_PV_YRS = 20
LIFE_BATT_YRS = 10
LIFE_INV_YRS = 10
LIFE_GEN_YRS = 10

NASA_POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/climatology/point"
    "?parameters=ALLSKY_SFC_SW_DWN&community=RE&longitude={lon}&latitude={lat}&format=JSON"
)


def crf(rate: float, n_years: int) -> float:
    """Capital recovery factor."""
    if rate <= 0:
        return 1.0 / n_years
    r1 = (1 + rate) ** n_years
    return rate * r1 / (r1 - 1)

def round_up_to_step(x: float, step: float) -> float:
    return math.ceil(x / step) * step

def fetch_nasa_ghi(lat: float, lon: float) -> dict:
    """Fetch monthly GHI climatology from NASA POWER. Returns dict month->value and list of values."""
    url = NASA_POWER_URL.format(lat=lat, lon=lon)
    resp = requests.get(url, timeout=12)
    resp.raise_for_status()
    data = resp.json()
    param = data.get("properties", {}).get("parameter", {}).get("ALLSKY_SFC_SW_DWN")
    if not param or not isinstance(param, dict):
        raise ValueError("NASA POWER: missing ALLSKY_SFC_SW_DWN")
    months_order = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
    values = [float(param[m]) for m in months_order if m in param]
    if len(values) != 12:
        raise ValueError("NASA POWER: expected 12 monthly GHI values")
    return {"monthly": param, "values": values}

def size_system(lat: float, lon: float, load_kwh_day: float,
                fuel_cost_usd_per_l: float,
                solar_fraction: float,
                autonomy_days: float,
                load_factor: float):
    nasa = fetch_nasa_ghi(lat, lon)
    ghi_vals = nasa["values"]
    ghi_worst = min(ghi_vals)
    ghi_median = statistics.median(ghi_vals)

    # PV energy per kW per day (worst-month design)
    e_pv_per_kw_day = ghi_worst * PR
    if e_pv_per_kw_day <= 0:
        raise ValueError("Computed zero PV output; invalid GHI.")

    # PV capacity sized to meet specified renewables energy fraction annually (heuristic using worst-month)
    pv_kw = (load_kwh_day * solar_fraction) / e_pv_per_kw_day

    # Reliability bump for strong seasonality
    seasonality_ratio = (ghi_median / ghi_worst) if ghi_worst > 0 else 1.0
    if seasonality_ratio > 1.4:
        pv_kw *= 1.15

    # Battery sizing
    batt_kwh = (load_kwh_day * autonomy_days) / BATTERY_EFFECTIVE

    # Peak and generator sizing
    peak_kw = load_kwh_day / (24.0 * max(0.05, load_factor))
    gen_kw = GENERATOR_SF * peak_kw

    # Inverter sizing
    inverter_kw = max(peak_kw, INVERTER_UTIL_KW_PER_PV * pv_kw)

    # BoM counts
    panel_count = math.ceil(pv_kw * 1000.0 / PANEL_WATTS)
    battery_count = math.ceil(batt_kwh / BATTERY_UNIT_KWH)

    # Annual energies
    annual_load = load_kwh_day * 365.0
    annual_pv_energy = pv_kw * e_pv_per_kw_day * 365.0
    served_by_pv_batt = min(annual_load, annual_pv_energy) * PV_UTILIZATION
    served_by_gen = max(0.0, annual_load - served_by_pv_batt)

    # Fuel
    liters_per_kwh = GEN_SPEC_CONS_L_PER_KWH
    annual_fuel_liters = served_by_gen * liters_per_kwh
    annual_fuel_cost = annual_fuel_liters * fuel_cost_usd_per_l

    # CAPEX
    capex_pv = pv_kw * COST_PV_PER_KW
    capex_batt = batt_kwh * COST_BATT_PER_KWH
    capex_inv = inverter_kw * COST_INV_PER_KW
    gen_nameplate_kw = round_up_to_step(gen_kw, 5.0)
    capex_gen = gen_nameplate_kw * COST_GEN_PER_KW

    capex_total = capex_pv + capex_batt + capex_inv + capex_gen

    # Annual O&M
    annual_om = (pv_kw * OM_PV_PER_KW_YR) + (batt_kwh * OM_BATT_PER_KWH_YR) + (gen_nameplate_kw * OM_GEN_PER_KW_YR)

    # Annualized CAPEX (equivalent annual cost)
    def annualize(capex, life):
        return capex * crf(WACC, life)

    annualized_pv = annualize(capex_pv, LIFE_PV_YRS)
    annualized_batt = annualize(capex_batt, LIFE_BATT_YRS)
    annualized_inv = annualize(capex_inv, LIFE_INV_YRS)
    annualized_gen = annualize(capex_gen, LIFE_GEN_YRS)

    total_annual_cost = annualized_pv + annualized_batt + annualized_inv + annualized_gen + annual_om + annual_fuel_cost
    lcoe = total_annual_cost / annual_load if annual_load > 0 else float("inf")

    # Warnings
    warnings = []
    if ghi_worst < 1.5:
        warnings.append("Low winter sun (worst-month GHI < 1.5 kWh/m²/day): expect significant generator runtime.")
    if seasonality_ratio > 1.4:
        warnings.append("High seasonality detected: PV capacity increased by 15% for reliability.")
    if solar_fraction >= 0.95 and autonomy_days < 1.0:
        warnings.append("For very high renewables targets, consider ≥1 day autonomy for resilience.")
    if inverter_kw < peak_kw:
        warnings.append("Inverter undersized vs. peak load; increase inverter rating.")

    # Round displayed values
    def rnd(x, nd=1):
        return round(float(x), nd)

    result = {
        "ghi_worst": rnd(ghi_worst, 2),
        "ghi_median": rnd(ghi_median, 2),
        "e_pv_per_kw_day": rnd(e_pv_per_kw_day, 3),
        "pv_kw": rnd(pv_kw, 1),
        "batt_kwh": rnd(batt_kwh, 0),
        "inverter_kw": rnd(inverter_kw, 0),
        "gen_kw": rnd(gen_nameplate_kw, 0),
        "panel_count": int(panel_count),
        "panel_w": PANEL_WATTS,
        "battery_count": int(battery_count),
        "battery_unit_kwh": BATTERY_UNIT_KWH,
        "annual_load": rnd(annual_load, 0),
        "annual_pv_energy": rnd(annual_pv_energy, 0),
        "served_by_pv_batt": rnd(served_by_pv_batt, 0),
        "served_by_gen": rnd(served_by_gen, 0),
        "annual_fuel_liters": rnd(annual_fuel_liters, 0),
        "annual_fuel_cost": rnd(annual_fuel_cost, 0),
        "capex_pv": rnd(capex_pv, 0),
        "capex_batt": rnd(capex_batt, 0),
        "capex_inv": rnd(capex_inv, 0),
        "capex_gen": rnd(capex_gen, 0),
        "capex_total": rnd(capex_total, 0),
        "annual_om": rnd(annual_om, 0),
        "annualized_pv": rnd(annualized_pv, 0),
        "annualized_batt": rnd(annualized_batt, 0),
        "annualized_inv": rnd(annualized_inv, 0),
        "annualized_gen": rnd(annualized_gen, 0),
        "total_annual_cost": rnd(total_annual_cost, 0),
        "lcoe": round(lcoe, 2),
        "warnings": warnings,
    }
    return result

def parse_float(name: str, value: str, min_val=None, max_val=None):
    try:
        v = float(value)
    except Exception:
        raise ValueError(f"Invalid number for {name}")
    if min_val is not None and v < min_val:
        raise ValueError(f"{name} must be ≥ {min_val}")
    if max_val is not None and v > max_val:
        raise ValueError(f"{name} must be ≤ {max_val}")
    return v

@app.route("/api/plan", methods=["POST"])
def plan():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing JSON request body"}), 400

        lat = parse_float("Latitude", data.get("lat", ""), -90, 90)
        lon = parse_float("Longitude", data.get("lon", ""), -180, 180)
        load = parse_float("Daily load (kWh/day)", data.get("load", ""), 0.1, None)

        fuel_cost = data.get("fuel_cost", FUEL_COST_DEFAULT)
        fuel_cost = float(fuel_cost) if fuel_cost != "" else FUEL_COST_DEFAULT

        r_target = float(data.get("renewables_target", list(RENEWABLES_TARGETS.values())[1]))
        autonomy = float(data.get("autonomy_days", list(AUTONOMY_OPTIONS.values())[1]))
        load_factor = float(data.get("load_factor", list(LOAD_TYPES.values())[0]))

        result = size_system(
            lat=lat, lon=lon,
            load_kwh_day=load,
            fuel_cost_usd_per_l=fuel_cost,
            solar_fraction=r_target,
            autonomy_days=autonomy,
            load_factor=load_factor
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    # For local dev: python app.py, then open http://127.0.0.1:5000
    app.run(host="0.0.0.0", port=5000, debug=True)