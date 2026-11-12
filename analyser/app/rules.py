"""Selection rules shared by the research scripts and the web app.

Body-control command = a user message that names a body part (window, curtain, hatch, trunk)
in Russian or Uzbek AND has exactly one direction (open or close). Messages with only the noun
(e.g. garbled "Oynani yo'q") are not selected, so counts are a lower bound.

Exchange = user message + the assistant record that immediately follows it for the same
`usersid_hash` in (createdAt, id) order. This is a heuristic, not a confirmed dialogue turn.

Repeat = the next record of that key is a user message sent within REPEAT_WINDOW_S seconds after
the assistant reply, naming the same body parts with the same direction.
"""

import math
import re
from datetime import datetime

REPEAT_WINDOW_S = 120

NOUN = re.compile(
    r"\b(окн|окон|штор(?!м)|люк(?!с)|багажник)\w*|\b(oyna|parda|lyuk|bagaj|yukni|yukxona)\w*", re.I
)
OPEN = re.compile(r"\bоткр\w*|\boch\w*", re.I)
CLOSE = re.compile(r"\bзакр\w*|\byop\w*", re.I)
# Raise / lower: the direction depends on the part (raising a window closes it, lowering opens it;
# raising a curtain, hatch or trunk opens it).
RAISE = re.compile(r"\bподним\w*|\bko.tar\w*", re.I)
LOWER = re.compile(r"\bопуст\w*|\btush[iu]r\w*", re.I)
CLAIMS_DONE = re.compile(
    r"открыва|закрыва|поднима|опуска|ochaman|yopaman|ochyapman|yopyapman|ochdim|yopdim", re.I
)
# Action-like code leaked into the reply text while the `actions` field is empty.
EMBEDDED_CODE = re.compile(
    r"^\|[A-Z]\d(:\d+)?|[.!?…\"]\s*[A-Z]\d(:\d+)?(,[A-Z]\d(:\d+)?)*\s*$|[a-zа-я][A-Z]\d(:\d+)?\s*$"
)

SCOPES = {"all": "", "active": " WHERE deletedAt IS NULL"}


def _class(word):
    word = word.lower()
    if word.startswith(("окн", "окон", "oyna")):
        return "window"
    if word.startswith(("штор", "parda")):
        return "curtain"
    if word.startswith(("люк", "lyuk")):
        return "hatch"
    return "trunk"


def noun_class(text):
    """The first body part named in the text, or None."""
    m = NOUN.search(text)
    return _class(m.group(0)) if m else None


def noun_set(text):
    """All body parts named in the text (used so a repeat must name the same parts)."""
    return frozenset(_class(m.group(0)) for m in NOUN.finditer(text))


def polarity(text):
    """'open' / 'close' if the text has exactly one direction, otherwise None."""
    noun = noun_class(text)
    raise_dir, lower_dir = ("close", "open") if noun == "window" else ("open", "close")
    found = set()
    if OPEN.search(text):
        found.add("open")
    if CLOSE.search(text):
        found.add("close")
    if RAISE.search(text):
        found.add(raise_dir)
    if LOWER.search(text):
        found.add(lower_dir)
    return found.pop() if len(found) == 1 else None


def has_action(actions):
    return actions.strip("|") != ""


def wilson(k, n, z=1.96):
    """95% Wilson interval for a share k/n. Assumes independent messages, so it is optimistic."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    center = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return center - half, center + half


def _seconds_between(earlier, later):
    """Seconds between two naive "YYYY-MM-DD HH:MM:SS" strings. The timezone is undocumented,
    so no zone or DST conversion is applied."""
    fmt = "%Y-%m-%d %H:%M:%S"
    return (datetime.strptime(later, fmt) - datetime.strptime(earlier, fmt)).total_seconds()


def body_exchanges(con, scope="all"):
    """Return one dict per body-control command with its reply and repeat flag.

    `scope` is 'all' (whole corpus) or 'active' (deletedAt IS NULL). Pairing is done inside the
    chosen scope, so the same message can have a different neighbour in each scope.
    """
    rows = con.execute(
        "SELECT id, usersid_hash, role, text, actions, createdAt, userLanguage FROM records"
        + SCOPES[scope]
        + " ORDER BY usersid_hash, createdAt, id"
    ).fetchall()
    out = []
    for i, u in enumerate(rows):
        if u[2] != "user":
            continue
        noun, pol = noun_class(u[3]), polarity(u[3])
        if not (noun and pol):
            continue
        reply = rows[i + 1] if i + 1 < len(rows) and rows[i + 1][1] == u[1] and rows[i + 1][2] == "assistant" else None
        nxt = rows[i + 2] if reply and i + 2 < len(rows) else None
        repeat = bool(
            nxt
            and nxt[1] == u[1]
            and nxt[2] == "user"
            and _seconds_between(reply[5], nxt[5]) <= REPEAT_WINDOW_S
            and noun_set(nxt[3]) == noun_set(u[3])
            and polarity(nxt[3]) == pol
        )
        out.append(
            {
                "id": u[0], "user": u[1], "text": u[3], "created": u[5], "lang": u[6],
                "noun": noun, "polarity": pol,
                "reply_id": reply[0] if reply else None,
                "reply_text": reply[3] if reply else None,
                "reply_actions": reply[4] if reply else None,
                "has_action": has_action(reply[4]) if reply else None,
                "repeat": repeat,
                "next_id": nxt[0] if repeat else None,
            }
        )
    return out
