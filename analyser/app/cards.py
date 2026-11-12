"""Research card definitions: selection rule, counts, example ids, counterexample, proposal.

Numbers are computed from the database for the chosen scope (whole corpus / deletedAt=null),
so a card never shows a number that belongs to another scope.
"""

import random
from collections import Counter
from functools import lru_cache

from . import rules
from .db import SCOPE_SQL, connect, short_key

SEED = 20261105
CARD_SCOPES = ("all", "active")
MIN_GROUP = 30  # below this many replies in a group the comparison is reported as insufficient
LONG_TEXT = 80

NOUN_LABEL = {"window": "окна", "curtain": "шторки", "hatch": "люк", "trunk": "багажник"}

CARDS = {
    "need": {
        "kind": "Потребность",
        "title": "Голосовое управление окнами, шторками, люком и багажником",
        "summary": "Люди регулярно просят открыть или закрыть окна, шторки, люк и багажник — на русском и узбекском.",
    },
    "hypothesis": {
        "kind": "Гипотеза",
        "title": "Ответ без кода action → пользователь повторяет команду",
        "summary": "После ответа без кода в actions пользователь чаще повторяет ту же команду в течение 120 секунд.",
    },
}


@lru_cache(maxsize=4)
def _exchanges(scope):
    con = connect()
    try:
        return rules.body_exchanges(con, scope)
    finally:
        con.close()


def _prepare(scope, exclude_top):
    ex = _exchanges(scope)
    per = Counter(e["user"] for e in ex)
    top, top_n = per.most_common(1)[0] if per else (None, 0)
    if exclude_top and top:
        ex = [e for e in ex if e["user"] != top]
    return ex, top, top_n


def _base(scope, excluded_key):
    con = connect()
    try:
        sql = f"SELECT COUNT(*), COUNT(DISTINCT usersid_hash) FROM records WHERE role = 'user' AND {SCOPE_SQL[scope]}"
        params = ()
        if excluded_key:
            sql += " AND usersid_hash <> ?"
            params = (excluded_key,)
        return con.execute(sql, params).fetchone()
    finally:
        con.close()


def _period(ex):
    return (min(e["created"] for e in ex), max(e["created"] for e in ex)) if ex else (None, None)


def _rate_row(label, group):
    n, k = len(group), sum(e["repeat"] for e in group)
    lo, hi = rules.wilson(k, n)
    return {
        "label": label, "n": n, "repeats": k,
        "rate": k / n if n else None, "lo": lo, "hi": hi,
        "n_keys": len({e["user"] for e in group}),
    }


def matches(scope, exclude_top, only, page, size):
    """Body-control commands of the card scope, optionally narrowed, one page at a time."""
    ex, _, _ = _prepare(scope, exclude_top)
    if only in ("no_action", "no_action_repeat"):
        ex = [e for e in ex if e["reply_id"] is not None and not e["has_action"]]
    if only in ("repeat", "no_action_repeat"):
        ex = [e for e in ex if e["repeat"]]
    ex = sorted(ex, key=lambda e: e["id"])
    return len(ex), ex[(page - 1) * size: page * size]


def _scope_header(scope, exclude_top, ex, top, top_n):
    first, last = _period(ex)
    return {
        "scope": scope,
        "period": f"{first} — {last}" if first else "нет данных",
        "excluded": f"исключён самый активный ключ {short_key(top)} ({top_n} команд)" if exclude_top and top else None,
    }


def need_card(scope="all", exclude_top=False):
    ex, top, top_n = _prepare(scope, exclude_top)
    msgs, keys = _base(scope, top if exclude_top else None)
    users = {e["user"] for e in ex}
    per = Counter(e["user"] for e in ex)
    langs = Counter(e["lang"] or "(null)" for e in ex)
    parts = Counter(e["noun"] for e in ex)
    long_n = sum(1 for e in ex if len(e["text"].strip()) > LONG_TEXT)

    numbers = [
        {"label": "Подходящих пользовательских сообщений", "value": len(ex)},
        {"label": "Различных usersid_hash", "value": len(users)},
        {"label": "Доля от пользовательских сообщений области",
         "value": f"{len(ex) / msgs:.2%}" if msgs else "—",
         "note": f"знаменатель: {msgs} сообщений role=user, {keys} usersid_hash"},
        {"label": "По языку", "value": ", ".join(f"{k}: {v}" for k, v in langs.most_common())},
        {"label": "По элементу", "value": ", ".join(f"{NOUN_LABEL[k]}: {v}" for k, v in parts.most_common())},
        {"label": "Ключей с ≥3 такими сообщениями", "value": sum(1 for v in per.values() if v >= 3)},
        {"label": "Длинных сообщений (>%d символов)" % LONG_TEXT, "value": long_n,
         "note": "часто это фрагменты речи, а не чистая команда"},
    ]

    rng = random.Random(SEED)
    ru = [e for e in ex if e["lang"] == "ru-RU"]
    uz = [e for e in ex if e["lang"] == "uz-UZ"]
    chosen = rng.sample(ru, min(3, len(ru))) + rng.sample(uz, min(2, len(uz)))
    examples = [_example(e) for e in chosen]
    counters = [
        {"links": [("сообщение", e["id"])], "text": e["text"].strip()[:160],
         "note": "Длинный фрагмент речи с упоминанием элемента; не чистая команда. Такие срабатывания завышают число."}
        for e in sorted(ex, key=lambda e: -len(e["text"]))[:2]
    ]

    return {
        **_scope_header(scope, exclude_top, ex, top, top_n),
        "key": "need", **CARDS["need"],
        "observation": "В истории много коротких команд вида «закрой все окна», «открой шторку», «oynalarni och», «pardani yop».",
        "rule": (
            "Запись role=user, в тексте есть название элемента (окн*, штор*, люк*, багажник*; oyna*, parda*, lyuk*, "
            "bagaj*, yukni*, yukxona*) и ровно одно направление: откр*/och* или закр*/yop*; «поднять/опустить» "
            "(подним*, опуст*, ko'tar*, tushir*) учитываются по смыслу — поднять окно значит закрыть, опустить — открыть; "
            "для шторки, люка и багажника «поднять» значит открыть. "
            "Сообщения только с названием элемента не берутся (например, искажённое «Oynani yo'q»), поэтому число — нижняя оценка. "
            "Код правила: app/rules.py."
        ),
        "base": f"Область: {SCOPE_LABEL_HINT[scope]}; период по подходящим сообщениям; знаменатель — сообщения role=user в области. Это выборка 20% ключей, не весь продукт.",
        "numbers": numbers,
        "table": None,
        "examples": examples,
        "counters": counters,
        "verdict": None,
        "proposal": (
            "Собрать из самых частых формулировок (ru и uz) тестовый набор команд и регулярно измерять, "
            "на каких формулировках ответ приходит без кода action. Начать с узбекских вариантов — их мало в готовых наборах."
        ),
        "limits": [
            "usersid_hash — ключ, а не человек или автомобиль.",
            "Правило по ключевым словам: возможны ложные срабатывания на длинных фрагментах речи и пропуски искажённых команд.",
            "Подтверждения того, что действие выполнено устройством, в данных нет.",
        ],
        "matches_params": {"only": ""},
    }


def hypothesis_card(scope="all", exclude_top=False):
    ex, top, top_n = _prepare(scope, exclude_top)
    paired = [e for e in ex if e["reply_id"] is not None]
    act = [e for e in paired if e["has_action"]]
    noact = [e for e in paired if not e["has_action"]]
    claims = [e for e in noact if rules.CLAIMS_DONE.search(e["reply_text"])]
    other = [e for e in noact if not rules.CLAIMS_DONE.search(e["reply_text"])]
    embedded = [e for e in noact if rules.EMBEDDED_CODE.search(e["reply_text"])]
    clean = [e for e in noact if not rules.EMBEDDED_CODE.search(e["reply_text"])]

    table = [
        _rate_row("Ответ с кодом action", act),
        _rate_row("Ответ без кода action", noact),
        _rate_row("  из них: текст говорит, что делает («закрываю…»)", claims),
        _rate_row("  из них: другой текст (непонимание, уточнение)", other),
        _rate_row("Без кода action, без ответов с кодом внутри текста", clean),
    ]

    a, b = table[0], table[1]
    if min(a["n"], b["n"]) < MIN_GROUP:
        verdict = (f"Данных недостаточно: ответов с action {a['n']}, без action {b['n']} в этой области "
                   f"(нужно не меньше {MIN_GROUP} в каждой группе). Вывод не делается.")
    elif b["lo"] > a["hi"]:
        verdict = (f"Повторы после ответа без action чаще: {b['rate']:.1%} против {a['rate']:.1%}, доверительные интервалы не пересекаются. "
                   "Это сигнал, а не доказательство того, что команда не выполнена.")
    else:
        verdict = "Различие не подтверждено: интервалы пересекаются."

    numbers = [
        {"label": "Команд управления кузовом в области", "value": len(ex)},
        {"label": "Из них с ответом ассистента сразу следом", "value": len(paired)},
        {"label": "Различных usersid_hash", "value": len({e["user"] for e in ex})},
        {"label": "Ответов без action, где код оказался внутри текста", "value": f"{len(embedded)} из {len(noact)}",
         "note": "исключение таких ответов результат не меняет — см. последнюю строку таблицы"},
    ]

    rng = random.Random(SEED)
    hit = [e for e in noact if e["repeat"]]
    examples = [_example(e, with_repeat=True) for e in rng.sample(hit, min(4, len(hit)))]
    quiet = [e for e in claims if not e["repeat"]]
    counters = [
        {**_example(e), "note": "Ответ говорит «открываю», кода action нет, повтора нет. Возможно, команда выполнена, а код не передан: пустое actions ≠ невыполнение."}
        for e in rng.sample(quiet, min(2, len(quiet)))
    ]

    return {
        **_scope_header(scope, exclude_top, ex, top, top_n),
        "key": "hypothesis", **CARDS["hypothesis"],
        "observation": (
            "На одну и ту же команду («открой все окна») код в actions бывает разным или пустым. "
            "Если пустой actions значит «ничего не сделано», пользователь должен чаще повторять команду."
        ),
        "rule": (
            "Берутся команды управления кузовом из первой карточки, у которых сразу следом (тот же usersid_hash, порядок createdAt, id) идёт запись assistant. "
            "Ответ «с action» — поле actions непустое (кроме «|»). Повтор — следующая запись того же ключа role=user, "
            f"отправленная не позже {rules.REPEAT_WINDOW_S} с после ответа, с тем же элементом и тем же направлением. "
            "Соответствие «запрос → ответ» — эвристика, а не подтверждённый диалог."
        ),
        "base": "Знаменатель каждой строки — команды этой группы с ответом ассистента сразу следом. Выборка 20% ключей; доверительные интервалы Уилсона считают сообщения независимыми, поэтому оптимистичны.",
        "numbers": numbers,
        "table": table,
        "examples": examples,
        "counters": counters,
        "verdict": verdict,
        "proposal": (
            "Эксперимент: если на команду нет кода action, не говорить «закрываю», а сообщать «не получилось, повторить?». "
            "Метрика — доля повторов за 120 с. Параллельно выяснить у разработчиков, всегда ли код action отправляется при выполнении, "
            "и сверить с логами устройства."
        ),
        "limits": [
            "Повтор команды — наблюдение, а не доказательство ошибки: человек мог просто захотеть повторить.",
            "Группа без action мала, интервал широкий.",
            "Языки различаются: в ru-RU и uz-UZ причины ответов без action могут быть разными.",
            "Коды в actions без документации остаются гипотезой.",
        ],
        "matches_params": {"only": "no_action"},
    }


def _example(e, with_repeat=False):
    links = [("сообщение", e["id"])]
    if e["reply_id"]:
        links.append(("ответ", e["reply_id"]))
    if with_repeat and e["next_id"]:
        links.append(("повтор", e["next_id"]))
    reply = (e["reply_text"] or "").strip("| ")
    return {
        "links": links, "text": e["text"].strip()[:160],
        "reply": reply[:160] if e["reply_text"] is not None else None,
        "actions": e["reply_actions"],
    }


SCOPE_LABEL_HINT = {"all": "весь корпус", "active": "только deletedAt=null"}

BUILDERS = {"need": need_card, "hypothesis": hypothesis_card}
