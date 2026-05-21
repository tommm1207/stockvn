"""
tests/test_watchlist_manager.py – Unit tests for SQLite-backed WatchlistManager.

Uses a temporary SQLite database for each test to ensure isolation.
"""

import os
import sys
import sqlite3
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

# Add backend to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Create a temp SQLite DB for each test and patch database module."""
    db_path = tmp_path / "test_stockvn.db"
    # Patch environment and module-level variables before importing
    with patch.dict(os.environ, {"SQLITE_PATH": str(db_path)}):
        # Force re-import with new path
        import database
        # Override the module-level path
        database._DB_PATH = db_path
        # Clear thread-local to force new connection
        database._local.__dict__.clear()
        # Initialize schema
        database.init_db()
        yield db_path
        # Cleanup thread-local connection
        conn = getattr(database._local, "conn", None)
        if conn:
            conn.close()
            database._local.__dict__.clear()


@pytest.fixture
def wm():
    """Fresh WatchlistManager instance."""
    from watchlist_manager import WatchlistManager
    return WatchlistManager()


class TestAddSymbol:
    def test_add_new_symbol_returns_true(self, wm):
        assert wm.add_symbol("user1", "VNM") is True

    def test_add_duplicate_returns_false(self, wm):
        wm.add_symbol("user1", "VNM")
        assert wm.add_symbol("user1", "VNM") is False

    def test_add_same_symbol_different_users(self, wm):
        assert wm.add_symbol("user1", "VNM") is True
        assert wm.add_symbol("user2", "VNM") is True

    def test_add_normalizes_to_uppercase(self, wm):
        assert wm.add_symbol("user1", "vnm") is True
        assert wm.add_symbol("user1", "VNM") is False  # Already exists


class TestRemoveSymbol:
    def test_remove_existing_returns_true(self, wm):
        wm.add_symbol("user1", "VNM")
        assert wm.remove_symbol("user1", "VNM") is True

    def test_remove_nonexistent_returns_false(self, wm):
        assert wm.remove_symbol("user1", "VNM") is False

    def test_remove_one_user_keeps_other(self, wm):
        wm.add_symbol("user1", "VNM")
        wm.add_symbol("user2", "VNM")
        wm.remove_symbol("user1", "VNM")
        assert wm.get_user_watchlist("user2") == ["VNM"]


class TestGetUserWatchlist:
    def test_empty_watchlist(self, wm):
        assert wm.get_user_watchlist("unknown_user") == []

    def test_returns_all_symbols(self, wm):
        wm.add_symbol("user1", "VNM")
        wm.add_symbol("user1", "FPT")
        wm.add_symbol("user1", "HPG")
        result = wm.get_user_watchlist("user1")
        assert set(result) == {"VNM", "FPT", "HPG"}

    def test_preserves_insertion_order(self, wm):
        wm.add_symbol("user1", "HPG")
        wm.add_symbol("user1", "VNM")
        wm.add_symbol("user1", "FPT")
        result = wm.get_user_watchlist("user1")
        assert result == ["HPG", "VNM", "FPT"]


class TestGetAllUniqueSymbols:
    def test_no_duplicates(self, wm):
        wm.add_symbol("user1", "VNM")
        wm.add_symbol("user2", "VNM")
        wm.add_symbol("user1", "FPT")
        result = wm.get_all_unique_symbols()
        assert sorted(result) == ["FPT", "VNM"]

    def test_empty_when_no_data(self, wm):
        assert wm.get_all_unique_symbols() == []


class TestGetAllUsersForSymbol:
    def test_returns_correct_users(self, wm):
        wm.add_symbol("user1", "VNM")
        wm.add_symbol("user2", "VNM")
        wm.add_symbol("user3", "FPT")
        result = wm.get_all_users_for_symbol("VNM")
        assert sorted(result) == ["user1", "user2"]

    def test_no_users_for_unknown_symbol(self, wm):
        assert wm.get_all_users_for_symbol("XYZ") == []


class TestGetAllUsers:
    def test_returns_distinct_users(self, wm):
        wm.add_symbol("user1", "VNM")
        wm.add_symbol("user1", "FPT")
        wm.add_symbol("user2", "HPG")
        result = wm.get_all_users()
        assert sorted(result) == ["user1", "user2"]

    def test_empty_when_no_data(self, wm):
        assert wm.get_all_users() == []


class TestJsonMigration:
    def test_migrates_json_data(self, tmp_path):
        """Test that existing JSON watchlist data is migrated to SQLite."""
        import json
        import database

        # Reset migration flag
        conn = database.get_db()
        conn.execute("DELETE FROM app_metadata WHERE key = 'watchlist_json_migrated'")
        conn.commit()

        # Create a fake JSON file in the backend dir
        json_path = Path(database.__file__).parent / "watchlist_data.json"
        test_data = {"123456": ["VNM", "FPT"], "789": ["HPG"]}
        
        original_exists = json_path.exists()
        original_content = None
        if original_exists:
            original_content = json_path.read_text(encoding="utf-8")

        try:
            json_path.write_text(json.dumps(test_data), encoding="utf-8")
            
            # Re-run migration
            database._migrate_json_watchlist(conn)

            # Check data was migrated
            from watchlist_manager import WatchlistManager
            wm = WatchlistManager()
            assert set(wm.get_user_watchlist("123456")) == {"VNM", "FPT"}
            assert wm.get_user_watchlist("789") == ["HPG"]
        finally:
            # Restore original file state
            if original_exists and original_content is not None:
                json_path.write_text(original_content, encoding="utf-8")
            elif not original_exists and json_path.exists():
                json_path.unlink()


class TestDatabaseHealth:
    def test_health_check_ok(self):
        from database import check_db_health
        result = check_db_health()
        assert result["status"] == "ok"
        assert "watchlist_entries" in result
