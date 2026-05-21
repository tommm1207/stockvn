"""
database.py – SQLite connection & schema management for StockVN.

Tables:
  watchlists(user_id, symbol, created_at)
  trades(id, user_id, symbol, side, quantity, price, fee, trade_date, note, created_at)
  alert_rules(id, user_id, symbol, rule_type, operator, threshold, enabled, channel, cooldown_minutes, last_triggered_at, created_at)
  app_metadata(key, value)

Usage:
  from database import init_db, get_db
  init_db()          # Call once at startup
  db = get_db()      # Get a connection (reusable within same thread)
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).parent / "stockvn.db"
_DB_PATH = Path(os.getenv("SQLITE_PATH", str(_DEFAULT_DB_PATH)))

# Thread-local storage for connections (SQLite connections are not thread-safe)
_local = threading.local()
_lock = threading.RLock()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS watchlists (
    user_id    TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, symbol)
);

CREATE TABLE IF NOT EXISTS trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    side       TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity   REAL NOT NULL CHECK (quantity > 0),
    price      REAL NOT NULL CHECK (price > 0),
    fee        REAL NOT NULL DEFAULT 0,
    trade_date TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT NOT NULL,
    symbol            TEXT,
    rule_type         TEXT NOT NULL,
    operator          TEXT NOT NULL,
    threshold         REAL,
    enabled           INTEGER NOT NULL DEFAULT 1,
    channel           TEXT NOT NULL DEFAULT 'telegram',
    cooldown_minutes  INTEGER NOT NULL DEFAULT 60,
    last_triggered_at TEXT,
    created_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    """Get a thread-local SQLite connection."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return conn


def init_db():
    """Create tables if they don't exist, then run migrations."""
    conn = get_db()
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    logger.info(f"SQLite database initialized at {_DB_PATH}")
    _migrate_json_watchlist(conn)


def _migrate_json_watchlist(conn: sqlite3.Connection):
    """Migrate watchlist_data.json to SQLite if not already done."""
    row = conn.execute(
        "SELECT value FROM app_metadata WHERE key = ?",
        ("watchlist_json_migrated",),
    ).fetchone()
    if row and row["value"] == "true":
        return  # Already migrated

    json_path = Path(__file__).parent / "watchlist_data.json"
    if not json_path.exists():
        # No JSON file to migrate – mark as done
        conn.execute(
            "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, ?)",
            ("watchlist_json_migrated", "true"),
        )
        conn.commit()
        return

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("watchlist_data.json is not a dict, skipping migration")
            return

        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for user_id, symbols in data.items():
            if not isinstance(symbols, list):
                continue
            for symbol in symbols:
                if not isinstance(symbol, str):
                    continue
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO watchlists (user_id, symbol, created_at) VALUES (?, ?, ?)",
                        (str(user_id), symbol.upper(), now),
                    )
                    count += 1
                except sqlite3.IntegrityError:
                    pass  # Duplicate – skip

        conn.execute(
            "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, ?)",
            ("watchlist_json_migrated", "true"),
        )
        conn.commit()
        logger.info(f"Migrated {count} watchlist entries from JSON to SQLite")
    except Exception as e:
        logger.error(f"JSON watchlist migration failed: {e}")


def get_metadata(key: str) -> str | None:
    """Read a metadata value."""
    conn = get_db()
    row = conn.execute("SELECT value FROM app_metadata WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_metadata(key: str, value: str):
    """Write a metadata value."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO app_metadata (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


def check_db_health() -> dict:
    """Check database connectivity – used by /api/health."""
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        wl_count = conn.execute("SELECT COUNT(*) as cnt FROM watchlists").fetchone()["cnt"]
        trade_count = conn.execute("SELECT COUNT(*) as cnt FROM trades").fetchone()["cnt"]
        return {"status": "ok", "watchlist_entries": wl_count, "trade_entries": trade_count}
    except Exception as e:
        return {"status": "error", "error": str(e)}
