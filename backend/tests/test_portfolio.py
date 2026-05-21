import pytest
import sqlite3
import os

# Đặt biến môi trường trước khi import các module khác
test_db = "test_stockvn.db"
os.environ["SQLITE_PATH"] = test_db

from database import init_db
from portfolio_manager import PortfolioManager

@pytest.fixture
def setup_db():
    """Tạo database tạm cho test."""
    if os.path.exists(test_db):
        os.remove(test_db)
        
    init_db()
    
    yield test_db
    
    # Phục hồi
    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except:
            pass

    if os.path.exists(test_db):
        try:
            os.remove(test_db)
        except:
            pass

@pytest.fixture
def manager(setup_db):
    return PortfolioManager()

def test_add_and_get_holdings(manager):
    client_id = "test_user_1"
    
    # Mua 1000 HPG giá 25000
    manager.add_trade(client_id, "HPG", "BUY", 1000, 25000)
    
    holdings = manager.get_holdings(client_id)
    assert len(holdings) == 1
    assert holdings[0]['symbol'] == "HPG"
    assert holdings[0]['quantity'] == 1000
    assert holdings[0]['avg_cost'] == 25000
    
    # Mua thêm 1000 HPG giá 27000 (Trung bình giá lên)
    manager.add_trade(client_id, "HPG", "BUY", 1000, 27000)
    
    holdings = manager.get_holdings(client_id)
    assert holdings[0]['quantity'] == 2000
    assert holdings[0]['avg_cost'] == 26000  # (25000 + 27000) / 2

def test_sell_trades(manager):
    client_id = "test_user_2"
    
    manager.add_trade(client_id, "VNM", "BUY", 2000, 70000)
    
    # Bán 1000 VNM
    manager.add_trade(client_id, "VNM", "SELL", 1000, 72000)
    
    holdings = manager.get_holdings(client_id)
    assert len(holdings) == 1
    assert holdings[0]['quantity'] == 1000
    assert holdings[0]['avg_cost'] == 70000  # Giá vốn không đổi khi bán
    
    # Bán nốt 1000 VNM
    manager.add_trade(client_id, "VNM", "SELL", 1000, 75000)
    
    holdings = manager.get_holdings(client_id)
    assert len(holdings) == 0  # Hết hàng

def test_delete_trade_recalculates(manager):
    client_id = "test_user_3"
    
    trade1 = manager.add_trade(client_id, "SSI", "BUY", 1000, 30000)
    trade2 = manager.add_trade(client_id, "SSI", "BUY", 1000, 34000)
    
    holdings = manager.get_holdings(client_id)
    assert holdings[0]['avg_cost'] == 32000
    
    # Xóa giao dịch thứ 2
    manager.delete_trade(client_id, trade2['id'])
    
    holdings = manager.get_holdings(client_id)
    assert holdings[0]['quantity'] == 1000
    assert holdings[0]['avg_cost'] == 30000

def test_update_trade_rejects_invalid_values(manager):
    client_id = "test_user_4"
    trade = manager.add_trade(client_id, "HPG", "BUY", 1000, 25000)

    with pytest.raises(ValueError):
        manager.update_trade(client_id, trade["id"], quantity=-1)

    with pytest.raises(ValueError):
        manager.update_trade(client_id, trade["id"], price=0)

    with pytest.raises(ValueError):
        manager.update_trade(client_id, trade["id"], fee=-100)

def test_update_trade_rejects_oversell(manager):
    client_id = "test_user_5"
    buy = manager.add_trade(client_id, "FPT", "BUY", 1000, 90000)

    with pytest.raises(ValueError):
        manager.update_trade(client_id, buy["id"], side="SELL", quantity=1500)
