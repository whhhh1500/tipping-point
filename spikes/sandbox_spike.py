"""Sandbox spike: hold -> partial capture (lower amount) and hold -> void, with automated buyer approval.

Sandbox only. Credentials read from ~/.secrets (never printed). Every artifact is tiny and labelled TEST.
Writes a redacted request/response log to spikes/out/spike_<ts>.json.
"""
import json, os, sys, time, uuid, datetime
import httpx
from playwright.sync_api import sync_playwright

BASE = "https://api-m.sandbox.paypal.com"
RETURN = "https://example.com/tipping-point-test/return"
CANCEL = "https://example.com/tipping-point-test/cancel"
CUR = os.environ.get("SPIKE_CURRENCY", "SGD")
LOG = []

def env(path):
    d = {}
    for l in open(os.path.expanduser(path)):
        l = l.strip()
        if "=" in l and not l.startswith("#"):
            k, v = l.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d

app = env("~/.secrets/paypal_sandbox.env"); buyer = env("~/.secrets/paypal_sandbox_buyer.env")
assert "sandbox" in BASE
tok = httpx.post(BASE + "/v1/oauth2/token", auth=(app["PAYPAL_CLIENT_ID"], app["PAYPAL_CLIENT_SECRET"]),
                 data={"grant_type": "client_credentials"}, timeout=30).json()["access_token"]

def call(method, path, body=None):
    h = {"Authorization": "Bearer " + tok, "Content-Type": "application/json",
         "PayPal-Request-Id": str(uuid.uuid4()), "Prefer": "return=representation"}
    r = httpx.request(method, BASE + path, headers=h, json=body, timeout=60)
    try: data = r.json()
    except Exception: data = {"raw": r.text[:500]}
    LOG.append({"t": datetime.datetime.now().isoformat(timespec="seconds"), "req": f"{method} {path}", "body": body,
                "status": r.status_code, "debug_id": r.headers.get("paypal-debug-id"), "resp": data})
    print(f"{method} {path} -> {r.status_code}", data.get("status", data.get("name", "")))
    return r.status_code, data

def create_order(ref, value):
    return call("POST", "/v2/checkout/orders", {
        "intent": "AUTHORIZE",
        "purchase_units": [{"reference_id": ref, "description": "TEST ONLY - fake group buy hold",
                            "amount": {"currency_code": CUR, "value": value}}],
        "payment_source": {"paypal": {"experience_context": {
            "brand_name": "TIPPING POINT TEST", "shipping_preference": "NO_SHIPPING",
            "user_action": "CONTINUE", "return_url": RETURN, "cancel_url": CANCEL}}}})

def approve(url, page):
    """Drive sandbox buyer login + consent until redirected to RETURN."""
    page.goto(url, wait_until="domcontentloaded")
    t0 = time.time(); step = 0
    while time.time() - t0 < 150:
        if page.url.startswith(RETURN):
            return True
        step += 1
        try:
            if page.locator("#email").is_visible(timeout=1000) and page.locator("#email").input_value() == "":
                page.fill("#email", buyer["PAYPAL_SANDBOX_BUYER_EMAIL"])
                if page.locator("#btnNext").is_visible(timeout=1000): page.click("#btnNext")
                continue
        except Exception: pass
        try:
            if page.locator("#password").is_visible(timeout=1000):
                page.fill("#password", buyer["PAYPAL_SANDBOX_BUYER_PASSWORD"])
                page.click("#btnLogin"); page.wait_for_timeout(4000); continue
        except Exception: pass
        for sel in ["#payment-submit-btn", "button[data-id='payment-submit-btn']", "#consentButton",
                    "button:has-text('Continue to Review Order')", "button:has-text('Continue')",
                    "button:has-text('Agree & Continue')", "button:has-text('Complete Purchase')",
                    "button:has-text('Pay Now')", "button:has-text('Accept Cookies')", "#acceptAllButton"]:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=500):
                    loc.click(); page.wait_for_timeout(3000); break
            except Exception: pass
        page.wait_for_timeout(1500)
    page.screenshot(path=f"spikes/out/approve_fail_{int(time.time())}.png", full_page=True)
    return False

def run():
    results = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        ctx = br.new_context(locale="en-US")
        page = ctx.new_page()

        # Path 1: hold 30.00 -> capture LOWER 24.00 (final_capture) -> remainder released
        s, o = create_order("TEST-TP-PARTIAL", "30.00")
        link = next(l["href"] for l in o["links"] if l["rel"] in ("payer-action", "approve"))
        ok = approve(link, page); print("approved:", ok)
        if not ok: return {"error": "approval failed (path 1)"}
        s, a = call("POST", f"/v2/checkout/orders/{o['id']}/authorize", {})
        auth = a["purchase_units"][0]["payments"]["authorizations"][0]
        s, c = call("POST", f"/v2/payments/authorizations/{auth['id']}/capture",
                    {"amount": {"currency_code": CUR, "value": "24.00"}, "final_capture": True,
                     "invoice_id": f"TEST-TP-{uuid.uuid4().hex[:8]}", "note_to_payer": "TEST ONLY"})
        s, ag = call("GET", f"/v2/payments/authorizations/{auth['id']}")
        results["partial"] = {"order": o["id"], "auth": auth["id"], "auth_amount": auth["amount"],
                              "auth_status_initial": auth["status"], "capture_status": c.get("status"),
                              "capture_amount": c.get("amount"), "capture_id": c.get("id"),
                              "capture_breakdown": c.get("seller_receivable_breakdown"),
                              "auth_status_after": ag.get("status")}
        # Extra probe: a second capture on a finalized auth must fail (remainder released)
        s, c2 = call("POST", f"/v2/payments/authorizations/{auth['id']}/capture",
                     {"amount": {"currency_code": CUR, "value": "1.00"}, "final_capture": True})
        results["partial"]["second_capture_after_final"] = {"http": s, "name": c2.get("name"),
                                                           "issue": (c2.get("details") or [{}])[0].get("issue")}

        # Path 2: hold 30.00 -> void
        s, o2 = create_order("TEST-TP-VOID", "30.00")
        link2 = next(l["href"] for l in o2["links"] if l["rel"] in ("payer-action", "approve"))
        ok = approve(link2, page); print("approved:", ok)
        if not ok: results["void"] = {"error": "approval failed (path 2)"}; return results
        s, a2 = call("POST", f"/v2/checkout/orders/{o2['id']}/authorize", {})
        auth2 = a2["purchase_units"][0]["payments"]["authorizations"][0]
        s, v = call("POST", f"/v2/payments/authorizations/{auth2['id']}/void", None)
        s, ag2 = call("GET", f"/v2/payments/authorizations/{auth2['id']}")
        s, cv = call("POST", f"/v2/payments/authorizations/{auth2['id']}/capture",
                     {"amount": {"currency_code": CUR, "value": "1.00"}, "final_capture": True})
        results["void"] = {"order": o2["id"], "auth": auth2["id"], "void_http": s if False else None,
                           "auth_status_after": ag2.get("status"),
                           "capture_after_void": {"name": cv.get("name"), "issue": (cv.get("details") or [{}])[0].get("issue")}}
        br.close()
    return results

if __name__ == "__main__":
    res = run()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    json.dump({"currency": CUR, "results": res, "log": LOG}, open(f"spikes/out/spike_{ts}.json", "w"), indent=1)
    print(json.dumps(res, indent=1))
