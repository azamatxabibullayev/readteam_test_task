from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import cards, db

BASE = Path(__file__).parent

app = FastAPI(title="Analyser")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def url(path, **params):
    """Build a link, dropping empty parameters."""
    query = urlencode({k: v for k, v in params.items() if v not in (None, "", False, 0)})
    return f"{path}?{query}" if query else path


templates.env.globals.update(url=url, short_key=db.short_key, SCOPE_LABEL=db.SCOPE_LABEL, PAGE_SIZE=db.PAGE_SIZE)


def card_scope(scope):
    return scope if scope in cards.CARD_SCOPES else "all"


def record_scope(scope):
    return scope if scope in db.SCOPE_SQL else "all"


def pages(total, page):
    return {"page": page, "last": max((total + db.PAGE_SIZE - 1) // db.PAGE_SIZE, 1)}


@app.get("/")
def index(request: Request, scope: str = "all"):
    scope = card_scope(scope)
    con = db.connect()
    try:
        quality = db.quality(con, scope)
    finally:
        con.close()
    items = [builder(scope) for builder in cards.BUILDERS.values()]
    return templates.TemplateResponse(
        request, "index.html", {"scope": scope, "quality": quality, "cards": items, "scopes": cards.CARD_SCOPES}
    )


@app.get("/cards/{key}")
def card(request: Request, key: str, scope: str = "all", exclude_top: int = 0):
    if key not in cards.BUILDERS:
        raise HTTPException(404, "Карточка не найдена")
    scope = card_scope(scope)
    data = cards.BUILDERS[key](scope, bool(exclude_top))
    ids = [i for ex in data["examples"] + data["counters"] for _, i in ex["links"]]
    return templates.TemplateResponse(
        request, "card.html",
        {"card": data, "scope": scope, "exclude_top": int(bool(exclude_top)), "scopes": cards.CARD_SCOPES, "ids": ids},
    )


@app.get("/matches")
def matches(request: Request, scope: str = "all", exclude_top: int = 0, only: str = "", page: int = 1, card_key: str = "need"):
    scope = card_scope(scope)
    page = max(page, 1)
    total, rows = cards.matches(scope, bool(exclude_top), only, page, db.PAGE_SIZE)
    return templates.TemplateResponse(
        request, "matches.html",
        {"scope": scope, "exclude_top": int(bool(exclude_top)), "only": only, "rows": rows, "total": total,
         "card_key": card_key, **pages(total, page)},
    )


@app.get("/records")
def records(
    request: Request, q: str = "", role: str = "", lang: str = "",
    date_from: str = "", date_to: str = "", scope: str = "all", page: int = 1,
):
    scope = record_scope(scope)
    page = max(page, 1)
    con = db.connect()
    try:
        total, rows = db.search_records(con, q, role, lang, date_from, date_to, scope, page)
        langs = db.languages(con)
    finally:
        con.close()
    filters = {"q": q, "role": role, "lang": lang, "date_from": date_from, "date_to": date_to, "scope": scope}
    return templates.TemplateResponse(
        request, "records.html",
        {"filters": filters, "rows": rows, "total": total, "langs": langs + ["(null)"], **pages(total, page)},
    )


@app.get("/go")
def go(id: str = ""):
    id = id.strip()
    return RedirectResponse(f"/records/{id}" if id.isascii() and id.isdigit() else "/records")


@app.get("/records/{record_id}")
def record(request: Request, record_id: int):
    con = db.connect()
    try:
        rec = db.get_record(con, record_id)
        if rec is None:
            raise HTTPException(404, f"Запись id={record_id} не найдена")
        before, after = db.time_context(con, rec)
    finally:
        con.close()
    return templates.TemplateResponse(
        request, "record.html", {"rec": rec, "before": before, "after": after, "n": db.CONTEXT_SIZE}
    )
