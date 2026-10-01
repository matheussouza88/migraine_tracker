import pytest

from migraine_tracker import create_app
from migraine_tracker.database import db


@pytest.fixture
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "migraine_tracker"


def test_home_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Migraine Tracker" in response.data
    assert b"I Have a Migraine" in response.data
    assert b"Painkiller" in response.data
    assert b"Sumatriptan" in response.data


def test_status_endpoint_idle(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["is_active"] is False
    assert data["episode"] is None
    assert data["elapsed_seconds"] == 0


def test_migraine_episode_lifecycle(client):
    # 1. Start episode
    start_resp = client.post(
        "/api/start",
        json={"severity": "high", "notes": "Throbbing headache on left side"},
    )
    assert start_resp.status_code == 201
    start_data = start_resp.get_json()
    assert "started" in start_data["message"]
    ep_id = start_data["episode"]["id"]
    assert start_data["episode"]["is_active"] is True
    assert start_data["episode"]["severity"] == "high"

    # 2. Check active status
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data["is_active"] is True
    assert status_data["episode"]["id"] == ep_id

    # 3. Repeat start should be idempotent
    repeat_start = client.post("/api/start")
    assert repeat_start.status_code == 200
    assert "already in progress" in repeat_start.get_json()["message"]

    # 4. Finish episode
    finish_resp = client.post(
        "/api/finish",
        json={"notes": "Throbbing headache eased up after rest"},
    )
    assert finish_resp.status_code == 200
    finish_data = finish_resp.get_json()
    assert finish_data["episode"]["is_active"] is False
    assert finish_data["episode"]["duration_seconds"] is not None

    # 5. Check status is idle again
    status_resp_after = client.get("/api/status")
    assert status_resp_after.get_json()["is_active"] is False

    # 6. Check history contains completed episode
    hist_resp = client.get("/api/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.get_json()
    assert len(hist_data["episodes"]) == 1
    assert hist_data["episodes"][0]["id"] == ep_id

    # 7. Delete episode
    del_resp = client.delete(f"/api/history/episode/{ep_id}")
    assert del_resp.status_code == 200
    hist_data_empty = client.get("/api/history").get_json()
    assert len(hist_data_empty["episodes"]) == 0


def test_finish_without_active_episode(client):
    response = client.post("/api/finish")
    assert response.status_code == 400
    data = response.get_json()
    assert "No active migraine episode" in data["error"]


def test_medication_logging(client):
    # Log Painkiller
    pk_resp = client.post(
        "/api/medication",
        json={"medication_type": "painkiller", "dosage": "500mg Paracetamol"},
    )
    assert pk_resp.status_code == 201
    pk_data = pk_resp.get_json()
    assert pk_data["entry"]["medication_type"] == "Painkiller"
    assert pk_data["entry"]["dosage"] == "500mg Paracetamol"
    med_id_1 = pk_data["entry"]["id"]

    # Log Sumatriptan
    sm_resp = client.post(
        "/api/medication",
        json={"medication_type": "sumatriptan", "dosage": "50mg"},
    )
    assert sm_resp.status_code == 201
    sm_data = sm_resp.get_json()
    assert sm_data["entry"]["medication_type"] == "Sumatriptan"
    med_id_2 = sm_data["entry"]["id"]

    # Check History
    hist = client.get("/api/history").get_json()
    assert len(hist["medications"]) == 2

    # Delete Medication
    del_resp = client.delete(f"/api/history/medication/{med_id_1}")
    assert del_resp.status_code == 200
    hist_after = client.get("/api/history").get_json()
    assert len(hist_after["medications"]) == 1
    assert hist_after["medications"][0]["id"] == med_id_2


def test_invalid_medication_type(client):
    response = client.post(
        "/api/medication",
        json={"medication_type": "antibiotic"},
    )
    assert response.status_code == 400
    assert "Invalid medication type" in response.get_json()["error"]
