from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_and_reset():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["festival"] == "Riverside"

        r = client.post("/api/demo/reset", headers={"X-User": "jess"})
        assert r.status_code == 200
        body = r.json()
        assert body["sim_today"] == "2026-11-30"
        assert body["counts"]["stages"] == 3


def test_x_user_rejects_unknown():
    with TestClient(app) as client:
        r = client.post("/api/demo/reset", headers={"X-User": "mallory"})
        assert r.status_code == 400


def test_artists_and_inventory():
    with TestClient(app) as client:
        client.post("/api/demo/reset")
        artists = client.get("/api/artists").json()
        assert any(a["name"] == "Sparkle" and a["stage_name"] == "River Stage" for a in artists)
        inventory = client.get("/api/inventory").json()
        synth = [i for i in inventory if i["canonical_name"] == "Moog One analog synth"]
        assert synth and synth[0]["stage_id"] is None and synth[0]["quantity_total"] == 1
