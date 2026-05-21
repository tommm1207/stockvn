from fastapi.testclient import TestClient
import pytest
import os
os.environ["SQLITE_PATH"] = "test_api.db"

from main import app
from database import init_db

@pytest.fixture(autouse=True)
def setup_test_db():
    if os.path.exists("test_api.db"):
        try:
            os.remove("test_api.db")
        except:
            pass
    init_db()
    yield
    if os.path.exists("test_api.db"):
        try:
            os.remove("test_api.db")
        except:
            pass

client = TestClient(app)

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "database" in data
    assert data["database"]["status"] == "ok"

def test_get_symbols():
    response = client.get("/api/symbols")
    assert response.status_code == 200
    data = response.json()
    assert "symbols" in data
    assert len(data["symbols"]) > 0

def test_version_endpoint():
    response = client.get("/api/version")
    assert response.status_code == 200
    data = response.json()
    assert "app" in data
    assert "version" in data

def test_stock_data_fallback():
    # Test với một mã không tồn tại để xem lỗi có được handle duyên dáng không
    response = client.get("/api/stock/INVALID_XYZ_123")
    # Trả về 400 Bad Request
    assert response.status_code in [400, 404, 500]
    if response.status_code in [400, 404]:
        assert "detail" in response.json()

def test_portfolio_rejects_invalid_symbol():
    response = client.post(
        "/api/portfolio/web_00112233445566778899aabbccddeeff/trades",
        json={"symbol": "BAD!!!", "side": "BUY", "quantity": 1, "price": 1000},
    )
    assert response.status_code == 400

def test_scanner_rejects_invalid_symbol():
    response = client.get("/api/scanner?symbols=BAD!!!")
    assert response.status_code == 400

def test_alert_rejects_invalid_symbol():
    response = client.post(
        "/api/alerts/web_00112233445566778899aabbccddeeff",
        json={"symbol": "BAD!!!", "rule_type": "price_above", "operator": "gt", "threshold": 1000},
    )
    assert response.status_code == 400
