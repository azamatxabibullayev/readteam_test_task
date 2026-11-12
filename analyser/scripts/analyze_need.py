"""Research for card 1: a recurring user need. Defines the selection rule and counts.

Need: voice control of body parts (windows, curtains, hatch, trunk), in Russian and Uzbek.
Rule: see app/rules.py (`noun_class` and `polarity`).

Usage: python scripts/analyze_need.py [--db PATH]
"""

import argparse
import collections
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rules  # noqa: E402

SEED = 20261105


def report(con, scope):
    ex = rules.body_exchanges(con, scope)
    users_total = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT usersid_hash) FROM records WHERE role='user'"
        + (" AND deletedAt IS NULL" if scope == "active" else "")
    ).fetchone()
    keys = {e["user"] for e in ex}
    print(f"\n=== scope: {scope} ===")
    print(f"base: {users_total[0]} user messages, {users_total[1]} usersid_hash")
    print(f"matched: {len(ex)} messages ({len(ex) / users_total[0]:.2%} of base), {len(keys)} usersid_hash")
    print("by language:", dict(collections.Counter(e["lang"] for e in ex)))
    print("by body part:", dict(collections.Counter(e["noun"] for e in ex)))
    print("by direction:", dict(collections.Counter(e["polarity"] for e in ex)))
    per = collections.Counter(e["user"] for e in ex)
    if per:
        top_n = per.most_common(1)[0][1]
        rest = len(ex) - top_n
        print(f"most active key: {top_n} messages ({top_n / len(ex):.1%}); without it: {rest} messages, {len(keys) - 1} keys")
        print("keys with >=3 matched messages:", sum(1 for v in per.values() if v >= 3))
    return ex


def examples(ex):
    rng = random.Random(SEED)
    ru = [e for e in ex if e["lang"] == "ru-RU"]
    uz = [e for e in ex if e["lang"] == "uz-UZ"]
    print("\nexample ids (seed %d: 3 ru-RU, 2 uz-UZ):" % SEED)
    for e in rng.sample(ru, 3) + rng.sample(uz, 2):
        print(f"  id={e['id']} [{e['lang']}] {e['text'].strip()[:70]!r}")
    print("\nambiguous candidates (longest matched messages, likely not a clean command):")
    for e in sorted(ex, key=lambda e: -len(e["text"]))[:4]:
        print(f"  id={e['id']} [{e['lang']}] {e['text'].strip()[:110]!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "app.db")
    args = parser.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    ex_all = report(con, "all")
    report(con, "active")
    examples(ex_all)


if __name__ == "__main__":
    main()
