"""FastAPI web app. Run: uvicorn tipping_point.web:app --port 8000

Env: PAYPAL_MODE=fake|sandbox (default fake), PAYPAL_ENV_FILE (sandbox creds, default ~/.secrets/paypal_sandbox.env),
TP_BASE_URL (default http://127.0.0.1:8000), TP_READER=stub|gemini, PAYPAL_WEBHOOK_ID (hosted mode only).
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .campaign import RuleError
from .demo_runner import start_background
from .paypal import FakeHolds, PayPalError, SandboxHolds
from .readers import make_reader
from .service import SAMPLES, Service
from .settle import ApprovalError

class CreateReq(BaseModel):
    sample: str | None = None
    chat_text: str | None = None
    config: dict | None = None

class ChatReq(BaseModel):
    text: str

class BuyersReq(BaseModel):
    skip: list[str] = []

class SettleReq(BaseModel):
    plan_hash: str


STATIC = Path(__file__).resolve().parent.parent / "static"


def build_service() -> Service:
    mode = os.environ.get("PAYPAL_MODE", "fake")
    api = SandboxHolds.from_env_file(os.environ.get("PAYPAL_ENV_FILE", "~/.secrets/paypal_sandbox.env")) \
        if mode == "sandbox" else FakeHolds()
    return Service(api, os.environ.get("TP_BASE_URL", "http://127.0.0.1:8000"), make_reader(), mode=mode)


def create_app(service: Service | None = None) -> FastAPI:
    app = FastAPI(title="Tipping Point")
    app.state.svc = service or build_service()
    svc = lambda: app.state.svc

    def get(cid):
        if cid not in svc().campaigns:
            raise HTTPException(404, "no such campaign")
        return cid

    @app.exception_handler(PayPalError)
    def _pp(_, e: PayPalError):
        return JSONResponse({"error": "paypal", "issue": e.issue, "status": e.status}, status_code=502)

    @app.exception_handler(RuleError)
    def _rule(_, e):
        return JSONResponse({"error": "rule", "detail": str(e)}, status_code=422)

    @app.exception_handler(ApprovalError)
    def _appr(_, e):
        return JSONResponse({"error": "approval", "detail": str(e)}, status_code=409)

    @app.exception_handler(ValueError)
    def _val(_, e):
        return JSONResponse({"error": "invalid", "detail": str(e)}, status_code=409)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        return {"mode": svc().mode, "reader": svc().reader.name, "samples": list(SAMPLES)}


    @app.post("/api/campaigns")
    def create(req: CreateReq):
        try:
            st = svc().create(req.sample, req.chat_text, req.config)
        except RuleError:
            raise
        except (ArithmeticError, TypeError, ValueError, KeyError) as e:
            raise RuleError(f"could not read the campaign settings ({e.__class__.__name__})")
        return {"id": st.id, "chat_text": st.chat_text, "view": svc().view(st.id)}

    @app.get("/api/campaigns/{cid}")
    def view(cid: str):
        return svc().view(get(cid))

    @app.post("/api/campaigns/{cid}/read")
    def read(cid: str):
        svc().read(get(cid)); return svc().view(cid)


    @app.post("/api/campaigns/{cid}/chat")
    def chat(cid: str, req: ChatReq):
        svc().append_chat(get(cid), req.text); return svc().view(cid)

    @app.post("/api/campaigns/{cid}/holds")
    def holds(cid: str):
        svc().send_holds(get(cid)); return svc().view(cid)

    @app.post("/api/campaigns/{cid}/sync")
    def sync(cid: str):
        svc().sync(get(cid)); return svc().view(cid)


    @app.post("/api/campaigns/{cid}/demo-buyers")
    def demo_buyers(cid: str, req: BuyersReq | None = None):
        try:
            start_background(svc(), get(cid), skip=set((req.skip if req else [])))
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        return svc().view(cid)

    @app.post("/api/campaigns/{cid}/close")
    def close(cid: str):
        svc().close(get(cid)); return svc().view(cid)


    @app.post("/api/campaigns/{cid}/settle")
    def settle(cid: str, req: SettleReq):
        try:
            svc().settle(get(cid), req.plan_hash)
        except ApprovalError as e:
            raise HTTPException(409, str(e))
        return svc().view(cid)

    # --- buyer-facing return / cancel pages (PayPal redirects here)
    @app.get("/r/{cid}/{hid}", response_class=HTMLResponse)
    def returned(cid: str, hid: str):
        h = svc().on_return(get(cid), hid)
        c = svc().campaigns[cid].campaign
        return _page("Hold placed ✓", f"{c.currency} {h.amount} is <b>held, not charged</b>, for {h.qty} × {c.item}. "
                     f"You are only charged if the group reaches {c.moq}, at the final group price, which can only go down. "
                     f"If the group misses, the hold is released and you pay nothing.<br><small>Sandbox demo, no real money.</small>")

    @app.get("/x/{cid}/{hid}", response_class=HTMLResponse)
    def cancelled(cid: str, hid: str):
        svc().on_cancel(get(cid), hid)
        return _page("No hold placed", "You left PayPal without approving. Nothing was held.")

    @app.post("/api/webhooks/paypal")
    async def webhook(request: Request):
        event = await request.json()
        wid = os.environ.get("PAYPAL_WEBHOOK_ID")
        if not wid or not svc().api.verify_webhook({k.lower(): v for k, v in request.headers.items()}, event, wid):
            raise HTTPException(400, "unverified webhook")
        return {"result": svc().on_webhook(event)}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>{title}</title><link rel=stylesheet href="/static/style.css"></head>
<body class="buyer"><div class="buyer-card"><div class="logo">◔ Tipping Point</div><h1>{title}</h1><p>{body}</p></div></body></html>"""


app = create_app() if os.environ.get("TP_NO_APP") != "1" else None
