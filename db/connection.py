import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DB_PATH = PROJECT_ROOT / "data" / "tennis.db"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())