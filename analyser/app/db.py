"""SQLite connection and shared queries."""

import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

# Scope = which records are analysed. `deletedAt` is filled for most archive rows; the reason is unknown.
SCOPE_SQL = {"all": "1=1", "active": "deletedAt IS NULL", "deleted": "deletedAt IS NOT NULL"}
SCOPE_LABEL = {
    "all": "весь корпус",
    "active": "только deletedAt=null",
    "deleted": "только deletedAt заполнен",
}

PAGE_SIZE = 50
CONTEXT_SIZE = 5


def connect():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def short_key(usersid_hash):
    """Readable label for a long hash (not an identifier of a person or a car)."""
    return usersid_hash[7:15] if usersid_hash.startswith("$") else usersid_hash[:8]


def quality(con, scope):
    where = SCOPE_SQL[scope]
    one = lambda sql: con.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "total": one(f"SELECT COUNT(*) FROM records WHERE {where}"),
        "n_keys": one(f"SELECT COUNT(DISTINCT usersid_hash) FROM records WHERE {where}"),
        "roles": {r[0]: r[1] for r in con.execute(f"SELECT role, COUNT(*) FROM records WHERE {where} GROUP BY role")},
        "first": one(f"SELECT MIN(createdAt) FROM records WHERE {where}"),
        "last": one(f"SELECT MAX(createdAt) FROM records WHERE {where}"),
        "empty_text": one(f"SELECT COUNT(*) FROM records WHERE {where} AND TRIM(text) = ''"),
        "empty_actions": one(f"SELECT COUNT(*) FROM records WHERE {where} AND role = 'assistant' AND actions IN ('', '|')"),
        "assistant": one(f"SELECT COUNT(*) FROM records WHERE {where} AND role = 'assistant'"),
        "null_lang": one(f"SELECT COUNT(*) FROM records WHERE {where} AND userLanguage IS NULL"),
        "languages": [tuple(r) for r in con.execute(
            f"SELECT COALESCE(userLanguage, '(null)'), COUNT(*) FROM records WHERE {where} GROUP BY 1 ORDER BY 2 DESC"
        )],
    }


def languages(con):
    return [r[0] for r in con.execute("SELECT DISTINCT userLanguage FROM records WHERE userLanguage IS NOT NULL ORDER BY 1")]


def fts_query(q):
    """Turn free text into a safe FTS5 query: every word is a prefix term, all must match."""
    words = re.findall(r"\w+", q or "")
    return " ".join(f'"{w}"*' for w in words) or None


def search_records(con, q="", role="", lang="", date_from="", date_to="", scope="all", page=1):
    where, params = [SCOPE_SQL[scope].replace("deletedAt", "r.deletedAt")], []
    join = ""
    fts = fts_query(q)
    if fts:
        join = " JOIN records_fts f ON f.rowid = r.id"
        where.append("records_fts MATCH ?")
        params.append(fts)
    if role in ("user", "assistant"):
        where.append("r.role = ?")
        params.append(role)
    if lang == "(null)":
        where.append("r.userLanguage IS NULL")
    elif lang:
        where.append("r.userLanguage = ?")
        params.append(lang)
    if date_from:
        where.append("r.createdAt >= ?")
        params.append(date_from + " 00:00:00")
    if date_to:
        where.append("r.createdAt <= ?")
        params.append(date_to + " 23:59:59")
    clause = " AND ".join(where)
    total = con.execute(f"SELECT COUNT(*) FROM records r{join} WHERE {clause}", params).fetchone()[0]
    rows = con.execute(
        f"SELECT r.* FROM records r{join} WHERE {clause} ORDER BY r.createdAt DESC, r.id DESC LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, (max(page, 1) - 1) * PAGE_SIZE],
    ).fetchall()
    return total, rows


def get_record(con, record_id):
    return con.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()


def get_records(con, ids):
    ids = list(ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {r["id"]: r for r in con.execute(f"SELECT * FROM records WHERE id IN ({marks})", ids)}


def time_context(con, rec, n=CONTEXT_SIZE):
    """Nearest records of the same usersid_hash by (createdAt, id), regardless of scope."""
    before = con.execute(
        "SELECT * FROM records WHERE usersid_hash = ? AND (createdAt, id) < (?, ?) "
        "ORDER BY createdAt DESC, id DESC LIMIT ?",
        (rec["usersid_hash"], rec["createdAt"], rec["id"], n),
    ).fetchall()
    after = con.execute(
        "SELECT * FROM records WHERE usersid_hash = ? AND (createdAt, id) > (?, ?) "
        "ORDER BY createdAt, id LIMIT ?",
        (rec["usersid_hash"], rec["createdAt"], rec["id"], n),
    ).fetchall()
    return list(reversed(before)), after
