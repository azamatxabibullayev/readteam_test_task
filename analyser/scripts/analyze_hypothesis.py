"""Research for card 2: a tested hypothesis about a possible assistant problem.

Hypothesis: after a body-control command, if the assistant reply carries no action code,
the user repeats the same command within 120 s more often than when it carries one.
A repeat is only a signal; it does not prove the command failed.

Usage: python scripts/analyze_hypothesis.py [--db PATH]
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


def rate_line(label, group):
    n, k = len(group), sum(e["repeat"] for e in group)
    if n == 0:
        return f"  {label:34s} n=0"
    lo, hi = rules.wilson(k, n)
    users = len({e["user"] for e in group})
    return f"  {label:34s} n={n:5d} repeats={k:4d} rate={k / n:6.2%} CI95=[{lo:.1%},{hi:.1%}] keys={users}"


def report(ex, title):
    paired = [e for e in ex if e["reply_id"] is not None]
    act = [e for e in paired if e["has_action"]]
    noact = [e for e in paired if not e["has_action"]]
    print(f"\n--- {title} ---")
    print(f"  commands: {len(ex)}, with an assistant reply right after: {len(paired)}")
    print(rate_line("reply with action code", act))
    print(rate_line("reply without action code", noact))
    claims = [e for e in noact if rules.CLAIMS_DONE.search(e["reply_text"])]
    other = [e for e in noact if not rules.CLAIMS_DONE.search(e["reply_text"])]
    print(rate_line("  no action, text claims doing it", claims))
    print(rate_line("  no action, other text", other))
    return act, noact


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "app.db")
    args = parser.parse_args()
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)

    ex = rules.body_exchanges(con, "all")
    act, noact = report(ex, "scope: all (whole sample)")
    report(rules.body_exchanges(con, "active"), "scope: deletedAt IS NULL")

    # Defence check: drop the key with the most body-control commands in this card's scope.
    per = collections.Counter(e["user"] for e in ex)
    top, top_n = per.most_common(1)[0]
    report([e for e in ex if e["user"] != top], f"scope: all, without most active key ({top_n} commands)")

    print("\nby body part (all):")
    for noun in ("window", "curtain", "hatch", "trunk"):
        print(rate_line(f"{noun}: with action", [e for e in act if e["noun"] == noun]))
        print(rate_line(f"{noun}: without action", [e for e in noact if e["noun"] == noun]))

    print("\nby language (all):")
    for lang in ("ru-RU", "uz-UZ"):
        print(rate_line(f"{lang}: with action", [e for e in act if e["lang"] == lang]))
        print(rate_line(f"{lang}: without action", [e for e in noact if e["lang"] == lang]))

    rng = random.Random(SEED)
    print(f"\nexamples (seed {SEED}), no action AND repeated:")
    for e in rng.sample([e for e in noact if e["repeat"]], 4):
        print(f"  id={e['id']} -> reply id={e['reply_id']} -> repeat id={e['next_id']} | {e['text'].strip()[:50]!r} => {e['reply_text'][:60]!r}")

    print("\ncounterexamples:")
    quiet = [e for e in noact if not e["repeat"] and rules.CLAIMS_DONE.search(e["reply_text"])]
    for e in rng.sample(quiet, 2):
        print(f"  id={e['id']} reply id={e['reply_id']}: claims doing it, no action code, not repeated | {e['reply_text'][:70]!r}")
    embedded = [e for e in noact if rules.EMBEDDED_CODE.search(e["reply_text"])]
    clean = [e for e in noact if not rules.EMBEDDED_CODE.search(e["reply_text"])]
    print(f"  replies with an action-like code inside the text but empty actions field: {len(embedded)} of {len(noact)}")
    for e in embedded[:2]:
        print(f"    id={e['id']} reply id={e['reply_id']}: {e['reply_text'][:60]!r}")
    print(rate_line("  no action, without such replies", clean))


if __name__ == "__main__":
    main()
