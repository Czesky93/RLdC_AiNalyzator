import os
import tempfile

from fastapi.testclient import TestClient


def test_api_smoke():
    with tempfile.NamedTemporaryFile() as tmp:
        os.environ["DB_PATH"] = tmp.name
        os.environ["OFFLINE_MODE"] = "true"

        from main import app, init_db  # noqa: WPS433

        init_db()

        client = TestClient(app)
        health_resp = client.get("/health")
        assert health_resp.status_code == 200
        health_data = health_resp.json()
        assert health_data["status"] == "ok"
        assert "version" in health_data
        
        assert client.get("/api/summary").status_code == 200
        market = client.get("/api/market/summary")
        assert market.status_code == 200
        assert market.json()["liczba"] >= 1
        demo = client.get("/api/demo/summary")
        assert demo.status_code == 200
        blog = client.get("/api/blog")
        assert blog.status_code == 200
