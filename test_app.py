import pytest
from app import size_system

def test_size_system_basic():
    # Provide known dummy inputs to test the core logic execution
    lat = 12.3829
    lon = 77.3947
    buildings = 15
    area_sqm = 5000.0
    load_kwh_day = 1000.0
    fuel_cost = 1.20
    solar_fraction = 0.95
    autonomy = 1.0
    load_factor = 0.6

    res = size_system(lat, lon, buildings, area_sqm, load_kwh_day, fuel_cost, solar_fraction, autonomy, load_factor)

    assert res is not None
    assert "system_capacity" in res
    assert "capex_total" in res
    assert "reliability" in res
    assert res["area_sqm"] == 5000.0

def test_size_system_area_constraint():
    # Test with a very small area to force the area constraint logic
    res = size_system(
        lat=12.3829,
        lon=77.3947,
        buildings=15,
        area_sqm=50.0, # Very small area!
        load_kwh_day=1000.0,
        fuel_cost=1.20,
        solar_fraction=0.95,
        autonomy=1.0,
        load_factor=0.6
    )

    # 50 sqm / 5.0 sqm/kW = max 10 kW solar PV
    # The optimization engine should now cap solar and rely more on wind/biomass
    assert res["system_capacity"] > 0
    # Because solar is restricted, the mix should reflect heavy non-solar or a different financial outcome
    assert "energy_mix" in res
