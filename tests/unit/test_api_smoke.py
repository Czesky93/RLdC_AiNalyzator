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
        assert client.get("/health").status_code == 200
        assert client.get("/api/summary").status_code == 200
        market = client.get("/api/market/summary")
        assert market.status_code == 200
        assert market.json()["liczba"] >= 1
        demo = client.get("/api/demo/summary")
        assert demo.status_code == 200
        blog = client.get("/api/blog")
        assert blog.status_code == 200
