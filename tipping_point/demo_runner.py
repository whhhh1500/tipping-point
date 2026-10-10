"""Demo-only: play the buyers. Each fake buyer opens their real PayPal *sandbox* approval link.

The first buyer uses the existing sandbox wallet account; the others use PayPal's hosted guest checkout
with a sandbox test card (no accounts are created). The browser then lands on our /r/ return URL, which is
where the app itself places the hold, exactly as for a real buyer.
In fake mode (no network) buyers are approved in-process.
"""
from __future__ import annotations

import re
import threading
import time


def _guest_identity(participant: str, i: int):
    # PayPal rejects honorifics and single letters as names; sandbox identities are clearly fake anyway
    words = [w for w in re.sub(r"\(.*?\)|[^A-Za-z ]", " ", participant).split()
             if w.lower() not in {"mr", "mrs", "ms", "mdm", "dr", "uncle", "auntie", "aunty"} and len(w) > 1]
    first = (words[0] if words else "Buyer")[:20].title()
    last = (words[1] if len(words) > 1 else "Tester")[:20].title()
    email = f"{first.lower()}{i}.tp-sandbox-test@example.com"
    return first, last, email


def run_buyers(service, cid: str, pace_s: float = 0.6, headless: bool = True, skip: set | None = None,
               shot_dir: str | None = "spikes/out") -> list[dict]:
    st = service.campaigns[cid]
    pending = [h for h in sorted(st.holds.values(), key=lambda h: (h.created_at, h.participant))
               if h.status == "LINK_SENT" and h.participant not in (skip or set())]
    out = st.demo_log = []
    st.demo_progress = {"done": 0, "total": len(pending), "current": None}
    if service.mode == "fake":
        for h in pending:
            st.demo_progress["current"] = h.participant
            time.sleep(pace_s)
            service.api.approve(h.order_id)
            service.on_return(cid, h.id)
            h.payer = "fake"
            out.append({"participant": h.participant, "ok": True})
            st.demo_progress["done"] += 1
        st.demo_progress["current"] = None
        return out

    from playwright.sync_api import sync_playwright
    from .sandbox_buyers import approve_guest, approve_wallet
    prefix = f"{service.base_url}/r/{cid}/"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        wallet_used = any(h.payer == "wallet" for h in st.holds.values())
        for i, h in enumerate(pending):
            st.demo_progress["current"] = h.participant
            t0, ok, err = time.time(), False, None
            for attempt in range(2):                      # sandbox pages are occasionally slow: one retry
                ctx = browser.new_context(locale="en-US")
                page = ctx.new_page()
                try:
                    if not wallet_used:
                        ok = approve_wallet(page, h.approve_url, prefix); h.payer = "wallet"
                    else:
                        f, l, e = _guest_identity(h.participant, i)
                        ok = approve_guest(page, h.approve_url, prefix, f, l, e, timeout_s=90, shot_dir=shot_dir)
                        h.payer = "guest"
                except Exception as ex:  # noqa: BLE001 - demo tooling: record and retry
                    err = f"{type(ex).__name__}: {str(ex)[:160]}"
                    if shot_dir:
                        try:
                            page.screenshot(path=f"{shot_dir}/buyer_err_{h.id}_{attempt}.png", full_page=True)
                        except Exception:
                            pass
                ctx.close()
                if ok:
                    if h.payer == "wallet":
                        wallet_used = True
                    break
            if ok and h.status == "LINK_SENT":
                service.sync(cid)             # return page not reached in time: pick up the approval by polling
            out.append({"participant": h.participant, "ok": h.status == "HELD", "payer": h.payer,
                        "seconds": round(time.time() - t0, 1), "error": None if ok else (err or "did not finish approval")})
            st.demo_progress["done"] += 1
        st.demo_progress["current"] = None
        browser.close()
    return out


def start_background(service, cid: str, **kw) -> threading.Thread:
    st = service.campaigns[cid]
    if st.demo_running:
        raise RuntimeError("buyers already running")
    st.demo_running = True

    def go():
        try:
            run_buyers(service, cid, **kw)
        except Exception as ex:  # noqa: BLE001
            st.demo_log = (st.demo_log or []) + [{"participant": None, "ok": False, "error": str(ex)[:300]}]
        finally:
            st.demo_running = False
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t
