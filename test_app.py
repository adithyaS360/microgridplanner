import io

import pytest

import app as application
from models import db


@pytest.fixture(autouse=True)
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(application, "fetch_nasa_ghi", lambda lat, lon: [5.0] * 12)
    monkeypatch.setattr(application, "fetch_wind_speed", lambda lat, lon: 5.08)
    application.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}", RATELIMIT_ENABLED=False)
    with application.app.app_context():
        db.drop_all(); db.create_all()
    yield application.app.test_client()
    with application.app.app_context():
        db.session.remove(); db.drop_all()


def register_and_login(client, email="admin@example.com"):
    credentials = {"email": email, "password": "secure-password"}
    assert client.post("/api/auth/register", json=credentials).status_code == 201
    token = client.post("/api/auth/login", json=credentials).get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def create_project(client, headers):
    response = client.post("/api/projects", headers=headers, json={"name": "Campus", "lat": 12.38, "lon": 77.39, "assumptions": {"fuel_cost": 1.3}})
    assert response.status_code == 201
    return response.get_json()["id"]


def test_plan_validates_and_handles_p90(client):
    assert client.post("/api/plan", json={"load": "NaN"}).status_code == 400
    result = client.post("/api/plan", json={"weather_case": "P90", "renewables_target": 0.8}).get_json()
    assert result["weather_case"] == "P90"
    assert result["energy_mix"]["Solar"] + result["energy_mix"]["Wind"] >= 79.9


def test_project_analysis_profile_sensitivity_and_pdf(client):
    headers = register_and_login(client); project_id = create_project(client, headers)
    csv_data = "kwh\n" + "\n".join(["20"] * 24)
    profile = client.post(f"/api/projects/{project_id}/load-profiles", headers=headers, data={"file": (io.BytesIO(csv_data.encode()), "load.csv")}, content_type="multipart/form-data")
    assert profile.status_code == 201
    analysis = client.post(f"/api/projects/{project_id}/analyze", headers=headers, json={"load_profile_id": profile.get_json()["id"], "load": 480, "renewables_target": 0.8})
    assert analysis.status_code == 201
    analysis_id = analysis.get_json()["analysis_id"]
    sensitivity = client.post(f"/api/projects/{project_id}/sensitivity", headers=headers, json={"variable": "fuel_cost", "values": [0.9, 1.2]})
    assert sensitivity.status_code == 200
    assert len(sensitivity.get_json()["scenarios"]) == 2
    pdf = client.get(f"/api/projects/{project_id}/report/{analysis_id}.pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")


def test_tenant_isolation_roles_and_catalogs(client):
    first = register_and_login(client, "first@example.com"); second = register_and_login(client, "second@example.com")
    project_id = create_project(client, first)
    assert client.get(f"/api/projects/{project_id}", headers=second).status_code == 403
    assert client.post("/api/tariffs", headers=first, json={"name": "Grid", "energy_rate": 0.2}).status_code == 201
    assert len(client.get("/api/tariffs", headers=second).get_json()) == 0
    assert client.post("/api/incentives", headers=first, json={"region": "Karnataka", "name": "Solar support", "value": 0.1}).status_code == 201
    assert len(client.get("/api/incentives?region=Karnataka", headers=second).get_json()) == 1
    key = client.post("/api/api-keys", headers=first, json={"name": "integration"})
    assert key.status_code == 201 and key.get_json()["api_key"].startswith("mgp_")


def test_portfolio_and_finance(client):
    headers = register_and_login(client); project_id = create_project(client, headers)
    finance = client.post(f"/api/projects/{project_id}/financing", headers=headers, json={"debt_ratio": 0.7, "interest_rate": 0.08, "term_years": 12})
    assert finance.status_code == 201
    portfolio = client.get("/api/portfolio", headers=headers)
    assert portfolio.status_code == 200 and portfolio.get_json()[0]["project"]["id"] == project_id
