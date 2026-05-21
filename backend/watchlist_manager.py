"""
watchlist_manager.py – SQLite-backed watchlist storage.

Public API is unchanged from the JSON version so that main.py and
telegram_bot.py continue to work without modification.
"""

import logging
import threading
from datetime import datetime, timezone

from database import get_db

logger = logging.getLogger(__name__)
_lock = threading.RLock()


class WatchlistManager:
    def get_user_watchlist(self, chat_id: str) -> list:
        """Return list of symbols for a user."""
        conn = get_db()
        rows = conn.execute(
            "SELECT symbol FROM watchlists WHERE user_id = ? ORDER BY created_at",
            (str(chat_id),),
        ).fetchall()
        return [r["symbol"] for r in rows]

    def add_symbol(self, chat_id: str, symbol: str) -> bool:
        """Add symbol to user's watchlist. Returns True if added, False if duplicate."""
        with _lock:
            conn = get_db()
            key = str(chat_id)
            symbol = symbol.upper()
            # Check if already exists
            row = conn.execute(
                "SELECT 1 FROM watchlists WHERE user_id = ? AND symbol = ?",
                (key, symbol),
            ).fetchone()
            if row:
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO watchlists (user_id, symbol, created_at) VALUES (?, ?, ?)",
                (key, symbol, now),
            )
            conn.commit()
            return True

    def remove_symbol(self, chat_id: str, symbol: str) -> bool:
        """Remove symbol from user's watchlist. Returns True if removed."""
        with _lock:
            conn = get_db()
            key = str(chat_id)
            symbol = symbol.upper()
            cur = conn.execute(
                "DELETE FROM watchlists WHERE user_id = ? AND symbol = ?",
                (key, symbol),
            )
            conn.commit()
            return cur.rowcount > 0

    def get_all_unique_symbols(self) -> list:
        """Return all unique symbols across all users."""
        conn = get_db()
        rows = conn.execute("SELECT DISTINCT symbol FROM watchlists").fetchall()
        return [r["symbol"] for r in rows]

    def get_all_users_for_symbol(self, symbol: str) -> list:
        """Return all user IDs that watch a given symbol."""
        conn = get_db()
        rows = conn.execute(
            "SELECT user_id FROM watchlists WHERE symbol = ?",
            (symbol.upper(),),
        ).fetchall()
        return [r["user_id"] for r in rows]

    def get_all_users(self) -> list:
        """Return all distinct user IDs."""
        conn = get_db()
        rows = conn.execute("SELECT DISTINCT user_id FROM watchlists").fetchall()
        return [r["user_id"] for r in rows]
