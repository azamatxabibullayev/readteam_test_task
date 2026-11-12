"""Import threadhistories JSON into SQLite (data/app.db). Re-import must not duplicate rows.

Usage:
    python scripts/import_data.py [--src PATH_TO_JSON] [--db PATH_TO_DB]

The source file has one record per line, so it is read as a stream. Rows are keyed by the
original `id` (INSERT OR REPLACE), so importing the same file again leaves the count unchanged.
All fields are stored as in the source; dates stay as text ("YYYY-MM-DD HH:MM:SS"), and the
quality/type fields stay text because their scales are undocumented.
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = ROOT.parent / "assistant-test-20pct-users" / "data" / "threadhistories_20pct_users.json"
DEFAULT_DB = ROOT / "data" / "app.db"

COLUMNS = [
    "id", "usersid_hash", "role", "text", "actions", "createdAt", "updatedAt", "deletedAt",
    "timeSTT", "timeCache", "timeGPT", "userLanguage", "personality", "type", "internet",
    "user_request_type", "ai_response_type", "stt_quality", "ai_quality",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id                INTEGER PRIMARY KEY,
    usersid_hash      TEXT NOT NULL,
    role              TEXT NOT NULL,
    text              TEXT NOT NULL,
    actions           TEXT NOT NULL,
    createdAt         TEXT NOT NULL,
    updatedAt         TEXT NOT NULL,
    deletedAt         TEXT,
    timeSTT           REAL,
    timeCache         REAL,
    timeGPT           REAL,
    userLanguage      TEXT,
    personality       TEXT,
    type              TEXT,
    internet          INTEGER,
    user_request_type TEXT,
    ai_response_type  TEXT,
    stt_quality       TEXT,
    ai_quality        TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_user_time ON records (usersid_hash, createdAt, id);
CREATE INDEX IF NOT EXISTS idx_records_created   ON records (createdAt);
CREATE INDEX IF NOT EXISTS idx_records_role      ON records (role);
CREATE INDEX IF NOT EXISTS idx_records_lang      ON records (userLanguage);
CREATE INDEX IF NOT EXISTS idx_records_deleted   ON records (deletedAt);
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    text, content='records', content_rowid='id', tokenize='unicode61'
);
"""

BATCH = 10_000


def read_records(path):
    """Yield records one by one. Expects the layout `{"threadhistories":[` / one record per line / `]}`."""
    with open(path, encoding="utf-8") as f:
        first = f.readline().strip()
        if first != '{"threadhistories":[':
            raise ValueError(f"unexpected first line: {first[:80]!r}")
        for line in f:
            line = line.strip()
            if line == "]}":
                return
            yield json.loads(line.rstrip(","))


def import_file(src, db_path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    con.execute("PRAGMA synchronous = OFF")

    sql = f"INSERT OR REPLACE INTO records ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})"
    batch, seen = [], 0
    for rec in read_records(src):
        batch.append(tuple(rec[c] for c in COLUMNS))
        if len(batch) >= BATCH:
            con.executemany(sql, batch)
            seen += len(batch)
            batch.clear()
    if batch:
        con.executemany(sql, batch)
        seen += len(batch)

    # Rebuild the search index from the records table (idempotent on re-import).
    con.execute("INSERT INTO records_fts(records_fts) VALUES ('rebuild')")
    con.commit()
    return con, seen


def verify(con, src):
    profile = json.loads((src.parent / "dataset-profile.json").read_text(encoding="utf-8"))
    got = {
        "records": con.execute("SELECT COUNT(*) FROM records").fetchone()[0],
        "deletedAt_null": con.execute("SELECT COUNT(*) FROM records WHERE deletedAt IS NULL").fetchone()[0],
        "unique_usersid_hash": con.execute("SELECT COUNT(DISTINCT usersid_hash) FROM records").fetchone()[0],
        "user": con.execute("SELECT COUNT(*) FROM records WHERE role = 'user'").fetchone()[0],
        "assistant": con.execute("SELECT COUNT(*) FROM records WHERE role = 'assistant'").fetchone()[0],
    }
    expected = {
        "records": profile["records"],
        "deletedAt_null": profile["deletedAt_null"],
        "unique_usersid_hash": profile["unique_usersid_hash"],
        "user": profile["roles"]["user"],
        "assistant": profile["roles"]["assistant"],
    }
    ok = True
    for key, want in expected.items():
        status = "OK" if got[key] == want else "MISMATCH"
        ok &= got[key] == want
        print(f"  {key}: {got[key]} (expected {want}) {status}")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    started = time.perf_counter()
    con, seen = import_file(args.src, args.db)
    elapsed = time.perf_counter() - started
    print(f"Read {seen} records from {args.src.name} into {args.db} in {elapsed:.1f}s")

    ok = verify(con, args.src)
    con.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
