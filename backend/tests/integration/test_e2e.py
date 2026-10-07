from __future__ import annotations


def test_health_reports_core_dependencies(http):
    response = http.get("/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["deps"]["postgres"] is True
    assert body["deps"]["opensearch"] is True
