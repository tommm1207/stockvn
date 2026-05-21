"""
portfolio_manager.py – Portfolio tracking with SQLite storage.

Calculates holdings from trade history (no denormalization).
Supports BUY/SELL with average cost computation.
"""

import logging
import threading
from datetime import datetime, timezone

from database import get_db

logger = logging.getLogger(__name__)
_lock = threading.RLock()


class PortfolioManager:
    def add_trade(self, user_id: str, symbol: str, side: str, quantity: float,
                  price: float, fee: float = 0, trade_date: str = None,
                  note: str = None) -> dict:
        """Add a trade. Returns the created trade dict or raises ValueError."""
        symbol = symbol.upper()
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("side phải là BUY hoặc SELL")
        if quantity <= 0:
            raise ValueError("quantity phải > 0")
        if price <= 0:
            raise ValueError("price phải > 0")
        if fee < 0:
            raise ValueError("fee không được âm")

        # Check SELL doesn't exceed holding
        if side == "SELL":
            holdings = self.get_holdings(user_id)
            current_qty = 0
            for h in holdings:
                if h["symbol"] == symbol:
                    current_qty = h["quantity"]
                    break
            if quantity > current_qty:
                raise ValueError(
                    f"Không thể bán {quantity} {symbol} – chỉ đang nắm giữ {current_qty}"
                )

        if not trade_date:
            trade_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        now = datetime.now(timezone.utc).isoformat()

        with _lock:
            conn = get_db()
            cur = conn.execute(
                """INSERT INTO trades (user_id, symbol, side, quantity, price, fee, trade_date, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, symbol, side, quantity, price, fee, trade_date, note, now),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "user_id": user_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "fee": fee,
                "trade_date": trade_date,
                "note": note,
                "created_at": now,
            }

    def get_trades(self, user_id: str, symbol: str = None) -> list:
        """Get all trades for a user, optionally filtered by symbol."""
        conn = get_db()
        if symbol:
            rows = conn.execute(
                "SELECT * FROM trades WHERE user_id = ? AND symbol = ? ORDER BY trade_date, id",
                (user_id, symbol.upper()),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trades WHERE user_id = ? ORDER BY trade_date, id",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def update_trade(self, user_id: str, trade_id: int, **kwargs) -> bool:
        """Update a trade's fields. Returns True if updated."""
        allowed = {"symbol", "side", "quantity", "price", "fee", "trade_date", "note"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False

        if "symbol" in updates:
            updates["symbol"] = updates["symbol"].upper()
        if "side" in updates:
            updates["side"] = updates["side"].upper()
            if updates["side"] not in ("BUY", "SELL"):
                raise ValueError("side phải là BUY hoặc SELL")
        if "quantity" in updates and updates["quantity"] <= 0:
            raise ValueError("quantity phải > 0")
        if "price" in updates and updates["price"] <= 0:
            raise ValueError("price phải > 0")
        if "fee" in updates and updates["fee"] < 0:
            raise ValueError("fee không được âm")

        with _lock:
            conn = get_db()
            current = conn.execute(
                "SELECT * FROM trades WHERE user_id = ? AND id = ?",
                (user_id, trade_id),
            ).fetchone()
            if not current:
                return False

            merged = dict(current)
            merged.update(updates)
            merged["symbol"] = merged["symbol"].upper()
            merged["side"] = merged["side"].upper()
            if merged["side"] == "SELL":
                other_trades = conn.execute(
                    "SELECT * FROM trades WHERE user_id = ? AND id != ? ORDER BY trade_date, id",
                    (user_id, trade_id),
                ).fetchall()
                quantity = 0
                for t in other_trades:
                    if t["symbol"] != merged["symbol"]:
                        continue
                    quantity += t["quantity"] if t["side"] == "BUY" else -t["quantity"]
                if merged["quantity"] > quantity:
                    raise ValueError(
                        f"Không thể bán {merged['quantity']} {merged['symbol']} – chỉ đang nắm giữ {quantity}"
                    )

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [user_id, trade_id]
            cur = conn.execute(
                f"UPDATE trades SET {set_clause} WHERE user_id = ? AND id = ?",
                values,
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_trade(self, user_id: str, trade_id: int) -> bool:
        """Delete a trade. Returns True if deleted."""
        with _lock:
            conn = get_db()
            cur = conn.execute(
                "DELETE FROM trades WHERE user_id = ? AND id = ?",
                (user_id, trade_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_holdings(self, user_id: str) -> list:
        """Calculate current holdings from trade history.
        Returns list of {symbol, quantity, avg_cost, total_cost, total_fee}."""
        trades = self.get_trades(user_id)
        holdings = {}  # symbol -> {quantity, total_cost, total_fee}

        for t in trades:
            sym = t["symbol"]
            if sym not in holdings:
                holdings[sym] = {"quantity": 0, "total_cost": 0, "total_fee": 0}

            h = holdings[sym]
            if t["side"] == "BUY":
                h["total_cost"] += t["quantity"] * t["price"]
                h["quantity"] += t["quantity"]
                h["total_fee"] += t["fee"]
            elif t["side"] == "SELL":
                if h["quantity"] > 0:
                    # Reduce proportionally
                    sell_ratio = t["quantity"] / h["quantity"] if h["quantity"] > 0 else 0
                    h["total_cost"] -= h["total_cost"] * sell_ratio
                    h["quantity"] -= t["quantity"]
                    h["total_fee"] += t["fee"]

        result = []
        for sym, h in holdings.items():
            if h["quantity"] > 0.001:  # Float comparison tolerance
                avg_cost = h["total_cost"] / h["quantity"] if h["quantity"] > 0 else 0
                result.append({
                    "symbol": sym,
                    "quantity": round(h["quantity"], 0),
                    "avg_cost": round(avg_cost, 0),
                    "total_cost": round(h["total_cost"], 0),
                    "total_fee": round(h["total_fee"], 0),
                })
        return result

    def get_portfolio_summary(self, user_id: str, current_prices: dict = None) -> dict:
        """Get portfolio summary with P/L calculation.
        current_prices: {symbol: price} mapping for latest prices."""
        holdings = self.get_holdings(user_id)
        if not holdings:
            return {
                "holdings": [],
                "total_cost": 0,
                "total_value": 0,
                "total_pnl": 0,
                "total_pnl_pct": 0,
                "total_fee": 0,
            }

        prices = current_prices or {}
        total_cost = 0
        total_value = 0
        total_fee = 0

        for h in holdings:
            current_price = prices.get(h["symbol"], h["avg_cost"])
            market_value = h["quantity"] * current_price
            pnl = market_value - h["total_cost"]
            pnl_pct = (pnl / h["total_cost"] * 100) if h["total_cost"] > 0 else 0

            h["current_price"] = round(current_price, 0)
            h["market_value"] = round(market_value, 0)
            h["pnl"] = round(pnl, 0)
            h["pnl_pct"] = round(pnl_pct, 2)

            total_cost += h["total_cost"]
            total_value += market_value
            total_fee += h["total_fee"]

        # Calculate weight
        for h in holdings:
            h["weight"] = round(h["market_value"] / total_value * 100, 2) if total_value > 0 else 0

        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

        return {
            "holdings": holdings,
            "total_cost": round(total_cost, 0),
            "total_value": round(total_value, 0),
            "total_pnl": round(total_pnl, 0),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "total_fee": round(total_fee, 0),
        }
