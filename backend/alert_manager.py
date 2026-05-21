"""
alert_manager.py – Configurable alert rules with SQLite storage.

Supports:
  - Price above/below
  - RSI above/below
  - Score above/below
  - MACD bullish/bearish cross
  - Volume ratio above
  - Price crosses MA20/MA50

Cooldown prevents spam.
"""

import logging
import threading
from datetime import datetime, timezone, timedelta

from database import get_db

logger = logging.getLogger(__name__)
_lock = threading.RLock()

VALID_RULE_TYPES = {
    "price_above", "price_below",
    "rsi_above", "rsi_below",
    "score_above", "score_below",
    "macd_bullish", "macd_bearish",
    "volume_ratio_above",
    "price_above_ma20", "price_below_ma20",
    "price_above_ma50", "price_below_ma50",
}

VALID_OPERATORS = {"gt", "lt", "gte", "lte", "eq", "cross"}
VALID_CHANNELS = {"telegram", "web", "both"}


class AlertManager:
    def create_rule(self, user_id: str, rule_type: str, operator: str = "gt",
                    threshold: float = None, symbol: str = None,
                    channel: str = "telegram", cooldown_minutes: int = 60) -> dict:
        """Create an alert rule."""
        if rule_type not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type không hợp lệ. Hỗ trợ: {', '.join(sorted(VALID_RULE_TYPES))}")
        if operator not in VALID_OPERATORS:
            raise ValueError(f"operator không hợp lệ. Hỗ trợ: {', '.join(sorted(VALID_OPERATORS))}")
        if channel not in VALID_CHANNELS:
            raise ValueError(f"channel không hợp lệ. Hỗ trợ: {', '.join(sorted(VALID_CHANNELS))}")

        now = datetime.now(timezone.utc).isoformat()
        with _lock:
            conn = get_db()
            cur = conn.execute(
                """INSERT INTO alert_rules
                   (user_id, symbol, rule_type, operator, threshold, enabled, channel, cooldown_minutes, created_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (user_id, symbol.upper() if symbol else None, rule_type, operator,
                 threshold, channel, cooldown_minutes, now),
            )
            conn.commit()
            return {
                "id": cur.lastrowid,
                "user_id": user_id,
                "symbol": symbol.upper() if symbol else None,
                "rule_type": rule_type,
                "operator": operator,
                "threshold": threshold,
                "enabled": True,
                "channel": channel,
                "cooldown_minutes": cooldown_minutes,
                "created_at": now,
            }

    def get_rules(self, user_id: str) -> list:
        """Get all rules for a user."""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM alert_rules WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_rule(self, user_id: str, rule_id: int, **kwargs) -> bool:
        """Update a rule's fields."""
        allowed = {"symbol", "rule_type", "operator", "threshold", "enabled", "channel", "cooldown_minutes"}
        updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not updates:
            return False

        if "symbol" in updates and updates["symbol"]:
            updates["symbol"] = updates["symbol"].upper()
        if "rule_type" in updates and updates["rule_type"] not in VALID_RULE_TYPES:
            raise ValueError(f"rule_type không hợp lệ")
        if "channel" in updates and updates["channel"] not in VALID_CHANNELS:
            raise ValueError(f"channel không hợp lệ")

        with _lock:
            conn = get_db()
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [user_id, rule_id]
            cur = conn.execute(
                f"UPDATE alert_rules SET {set_clause} WHERE user_id = ? AND id = ?",
                values,
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_rule(self, user_id: str, rule_id: int) -> bool:
        """Delete a rule."""
        with _lock:
            conn = get_db()
            cur = conn.execute(
                "DELETE FROM alert_rules WHERE user_id = ? AND id = ?",
                (user_id, rule_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_enabled_rules(self) -> list:
        """Get all enabled rules across all users."""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM alert_rules WHERE enabled = 1",
        ).fetchall()
        return [dict(r) for r in rows]

    def check_rule(self, rule: dict, analysis: dict, current_price: float) -> bool:
        """Check if a rule matches current market data."""
        rt = rule["rule_type"]
        threshold = rule.get("threshold")
        indicators = analysis.get("indicators", {})

        if rt == "price_above":
            return current_price > threshold if threshold else False
        elif rt == "price_below":
            return current_price < threshold if threshold else False
        elif rt == "rsi_above":
            return indicators.get("rsi", 50) > threshold if threshold else False
        elif rt == "rsi_below":
            return indicators.get("rsi", 50) < threshold if threshold else False
        elif rt == "score_above":
            return analysis.get("score", 0) > threshold if threshold is not None else False
        elif rt == "score_below":
            return analysis.get("score", 0) < threshold if threshold is not None else False
        elif rt == "macd_bullish":
            return indicators.get("macd", {}).get("cross") == "bullish"
        elif rt == "macd_bearish":
            return indicators.get("macd", {}).get("cross") == "bearish"
        elif rt == "volume_ratio_above":
            return indicators.get("volume", {}).get("ratio", 1) > threshold if threshold else False
        elif rt == "price_above_ma20":
            ma20 = indicators.get("ma20")
            return current_price > ma20 if ma20 else False
        elif rt == "price_below_ma20":
            ma20 = indicators.get("ma20")
            return current_price < ma20 if ma20 else False
        elif rt == "price_above_ma50":
            ma50 = indicators.get("ma50")
            return current_price > ma50 if ma50 else False
        elif rt == "price_below_ma50":
            ma50 = indicators.get("ma50")
            return current_price < ma50 if ma50 else False
        return False

    def should_fire(self, rule: dict) -> bool:
        """Check if cooldown has elapsed since last trigger."""
        last = rule.get("last_triggered_at")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            cooldown = timedelta(minutes=rule.get("cooldown_minutes", 60))
            return datetime.now(timezone.utc) > last_dt + cooldown
        except (ValueError, TypeError):
            return True

    def mark_triggered(self, rule_id: int):
        """Update last_triggered_at for a rule."""
        now = datetime.now(timezone.utc).isoformat()
        with _lock:
            conn = get_db()
            conn.execute(
                "UPDATE alert_rules SET last_triggered_at = ? WHERE id = ?",
                (now, rule_id),
            )
            conn.commit()
