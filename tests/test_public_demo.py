import http.client
import json
import threading
from http.server import HTTPServer

from api.demo import handler


def test_public_demo_calls_bounded_policy_engine(tmp_path, monkeypatch):
    from api import demo

    monkeypatch.setattr(demo.db, "DB_PATH", tmp_path / "demo.sqlite3")
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        results = []
        for scenario in ("reference", "appointment", "payment", "identifier"):
            connection = http.client.HTTPConnection(*server.server_address)
            body = json.dumps({"scenario": scenario})
            connection.request(
                "POST",
                "/api/demo",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            results.append((response.status, json.loads(response.read())))
            connection.close()

        assert [status for status, _ in results] == [200, 200, 200, 200]
        assert [payload["decision"] for _, payload in results] == [
            "allowed",
            "requires_holder",
            "forbidden",
            "forbidden",
        ]
        assert all(payload["effect_written"] is False for _, payload in results)

        connection = http.client.HTTPConnection(*server.server_address)
        connection.request(
            "POST",
            "/api/demo",
            body=json.dumps({"scenario": "unknown", "trigger": "arbitrary input"}),
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 400
        assert "arbitrary input" not in response.read().decode("utf-8")
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
