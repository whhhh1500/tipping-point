"""Probe 2: multi-step partial captures (final_capture=false then true) and reauthorize inside honor period."""
import json, datetime, uuid
import spikes.sandbox_spike as S
from playwright.sync_api import sync_playwright
res = {}
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome", headless=True); page = br.new_context(locale="en-US").new_page()
    s, o = S.create_order("TEST-TP-MULTI", "20.00")
    link = next(l["href"] for l in o["links"] if l["rel"] in ("payer-action", "approve"))
    assert S.approve(link, page)
    s, a = S.call("POST", f"/v2/checkout/orders/{o['id']}/authorize", {})
    auth = a["purchase_units"][0]["payments"]["authorizations"][0]
    res["auth"] = {"id": auth["id"], "amount": auth["amount"], "expiration_time": auth.get("expiration_time")}
    s, r = S.call("POST", f"/v2/payments/authorizations/{auth['id']}/reauthorize", {"amount": {"currency_code": S.CUR, "value": "20.00"}})
    res["reauthorize_in_honor_period"] = {"http": s, "name": r.get("name"), "issue": (r.get("details") or [{}])[0].get("issue"), "status": r.get("status")}
    s, c1 = S.call("POST", f"/v2/payments/authorizations/{auth['id']}/capture", {"amount": {"currency_code": S.CUR, "value": "5.00"}, "final_capture": False})
    s, g1 = S.call("GET", f"/v2/payments/authorizations/{auth['id']}")
    s, c2 = S.call("POST", f"/v2/payments/authorizations/{auth['id']}/capture", {"amount": {"currency_code": S.CUR, "value": "7.00"}, "final_capture": True})
    s, g2 = S.call("GET", f"/v2/payments/authorizations/{auth['id']}")
    res["multi"] = {"c1": [c1.get("status"), c1.get("amount")], "auth_after_c1": g1.get("status"),
                    "c2": [c2.get("status"), c2.get("amount")], "auth_after_c2": g2.get("status")}
    br.close()
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
json.dump({"results": res, "log": S.LOG}, open(f"spikes/out/probe2_{ts}.json", "w"), indent=1)
print(json.dumps(res, indent=1))
