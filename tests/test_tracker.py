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


def test_status_endpoint(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["last_migraine"] is None
    assert data["last_medication"] is None
    assert data["total_migraines"] == 0
    assert data["total_medications"] == 0
    assert "server_time" in data


def test_migraine_instant_checkup(client):
    # 1. Log a migraine moment
    post_resp = client.post(
        "/api/migraine",
        json={"severity": "severe", "notes": "Sharp pain on temples"},
    )
    assert post_resp.status_code == 201
    post_data = post_resp.get_json()
    assert "recorded successfully" in post_data["message"]
    checkup = post_data["checkup"]
    assert checkup["severity"] == "severe"
    assert checkup["notes"] == "Sharp pain on temples"
    assert checkup["timestamp"] is not None
    checkup_id = checkup["id"]

    # 2. Verify status endpoint reflects latest checkup
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data["total_migraines"] == 1
    assert status_data["last_migraine"]["id"] == checkup_id

    # 3. Check history endpoint
    hist_resp = client.get("/api/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.get_json()
    assert len(hist_data["migraines"]) == 1
    assert hist_data["migraines"][0]["id"] == checkup_id

    # 4. Delete migraine record
    del_resp = client.delete(f"/api/history/migraine/{checkup_id}")
    assert del_resp.status_code == 200
    assert del_resp.get_json()["id"] == checkup_id

    # 5. History should now be empty
    hist_resp2 = client.get("/api/history")
    assert len(hist_resp2.get_json()["migraines"]) == 0


def test_update_migraine_severity(client):
    # 1. Create a checkup with default moderate severity
    post_resp = client.post("/api/migraine", json={})
    assert post_resp.status_code == 201
    checkup_id = post_resp.get_json()["checkup"]["id"]
    assert post_resp.get_json()["checkup"]["severity"] == "moderate"

    # 2. Update to mild
    patch_mild = client.patch(
        f"/api/migraine/{checkup_id}",
        json={"severity": "mild", "notes": "Mild pressure only"},
    )
    assert patch_mild.status_code == 200
    mild_data = patch_mild.get_json()
    assert mild_data["checkup"]["severity"] == "mild"
    assert mild_data["checkup"]["notes"] == "Mild pressure only"

    # 3. Update to severe
    patch_severe = client.patch(
        f"/api/migraine/{checkup_id}",
        json={"severity": "severe"},
    )
    assert patch_severe.status_code == 200
    assert patch_severe.get_json()["checkup"]["severity"] == "severe"

    # 4. Verify in history
    hist_resp = client.get("/api/history")
    assert hist_resp.status_code == 200
    migraines = hist_resp.get_json()["migraines"]
    assert len(migraines) == 1
    assert migraines[0]["severity"] == "severe"


def test_invalid_migraine_severity(client):
    # Reject invalid on POST
    post_resp = client.post("/api/migraine", json={"severity": "extreme"})
    assert post_resp.status_code == 400
    assert "Invalid severity level" in post_resp.get_json()["error"]

    # Create valid
    valid_resp = client.post("/api/migraine", json={"severity": "moderate"})
    checkup_id = valid_resp.get_json()["checkup"]["id"]

    # Reject invalid on PATCH
    patch_resp = client.patch(
        f"/api/migraine/{checkup_id}",
        json={"severity": "unbearable"},
    )
    assert patch_resp.status_code == 400
    assert "Invalid severity level" in patch_resp.get_json()["error"]

    # Nonexistent checkup PATCH
    not_found_resp = client.patch("/api/migraine/9999", json={"severity": "mild"})
    assert not_found_resp.status_code == 404
    assert "not found" in not_found_resp.get_json()["error"]


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

    # Check status endpoint
    status_resp = client.get("/api/status")
    status_data = status_resp.get_json()
    assert status_data["total_medications"] == 2
    assert status_data["last_medication"]["id"] == med_id_2

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


def test_delete_nonexistent_records(client):
    resp_mig = client.delete("/api/history/migraine/9999")
    assert resp_mig.status_code == 404
    assert "not found" in resp_mig.get_json()["error"]

    resp_med = client.delete("/api/history/medication/9999")
    assert resp_med.status_code == 404
    assert "not found" in resp_med.get_json()["error"]
