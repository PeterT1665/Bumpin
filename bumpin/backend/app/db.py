"""SQLite connection, schema and seed loader.

Seed files live in data/seed/<table>.json, each a JSON list of row objects.
Any team can add a seed file for a table without touching this module.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
SEED_DIR = DATA_DIR / "seed"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DB_PATH = Path(os.getenv("BUMPIN_DB", str(DATA_DIR / "bumpin.db")))

SIM_TODAY = "2026-11-30"

# Load order respects foreign keys. Tables without a seed file are skipped.
TABLES = [
    "festival",
    "stages",
    "inventory_items",
    "artists",
    "vendors",
    "emails",
    "tickets",
    "documents",
    "findings",
    "rider_items",
    "allocations",
    "outbox",
    "audit_log",
    "notifications",
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Connection that commits on success and rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


def row(cursor: sqlite3.Cursor) -> dict | None:
    r = cursor.fetchone()
    return dict(r) if r else None


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def drop_all(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in reversed(TABLES):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("PRAGMA foreign_keys = ON")


def load_seed(conn: sqlite3.Connection) -> dict[str, int]:
    """Insert every data/seed/<table>.json file. Returns row counts per table."""
    counts: dict[str, int] = {}
    for table in TABLES:
        path = SEED_DIR / f"{table}.json"
        if not path.exists():
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        for rec in records:
            rec = {k: _to_sql(v) for k, v in rec.items()}
            cols = ", ".join(rec)
            marks = ", ".join("?" for _ in rec)
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(rec.values()))
        counts[table] = len(records)
    return counts


def _to_sql(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


# Functions run after every reset, for demo state that needs code (e.g. a rider
# already on file). Register with POST_RESET_HOOKS.append(fn).
POST_RESET_HOOKS: list[Callable[[], None]] = []


def reset() -> dict[str, int]:
    """Drop, recreate and reseed the database, then set sim_today."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        drop_all(conn)
        init_schema(conn)
        counts = load_seed(conn)
        conn.execute("UPDATE festival SET sim_today = ?", (SIM_TODAY,))
    for hook in POST_RESET_HOOKS:
        hook()
    return counts


def ensure_ready() -> None:
    """On startup, build the database if it is missing or empty."""
    if DB_PATH.exists():
        with get_conn() as conn:
            init_schema(conn)
            has_festival = conn.execute("SELECT COUNT(*) FROM festival").fetchone()[0]
        if has_festival:
            return
    reset()


def festival() -> dict:
    with get_conn() as conn:
        return row(conn.execute("SELECT * FROM festival LIMIT 1")) or {}
