"""Multi-buyer end-to-end run against a running server in PAYPAL_MODE=sandbox. Writes spikes/out/e2e_<name>.json.
Usage: e2e_sandbox.py <base> <scenario: durian-miss | keycaps-topup>"""
import json, sys, time
import httpx

base, scen = sys.argv[1], sys.argv[2]
c = httpx.Client(base_url=base, timeout=60)


def wait_buyers(cid):
    c.post(f"/api/campaigns/{cid}/demo-buyers", json={})
    while True:
        v = c.get(f"/api/campaigns/{cid}").json()
        if not v["demo_running"]:
            return v
        time.sleep(3)


t0 = time.time()
sample = {"durian-miss": "durian", "keycaps-topup": "keycaps"}[scen]
cid = c.post("/api/campaigns", json={"sample": sample}).json()["id"]
c.post(f"/api/campaigns/{cid}/read")
c.post(f"/api/campaigns/{cid}/holds")
v = wait_buyers(cid)
snap = {"after_first_holds": {"held": v["progress"]["held"], "committed": v["progress"]["committed"], "demo_log": v["demo_log"]}}
if scen == "keycaps-topup":
    v = c.post(f"/api/campaigns/{cid}/chat", json={"text": "kai: +2 base"}).json()
    snap["after_chat_change"] = {r["participant"]: r["status"] for r in v["rows"]}
    v = c.post(f"/api/campaigns/{cid}/holds").json()
    snap["topup_links"] = [l for r in v["rows"] for l in r["links"] if l["kind"] == "top-up"]
    v = wait_buyers(cid)
    snap["after_topup"] = {"held": v["progress"]["held"], "demo_log": v["demo_log"]}
v = c.post(f"/api/campaigns/{cid}/close").json()
snap["plan"] = v["plan"]
v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": v["plan"]["hash"]}).json()
snap["final"] = {"totals": v["totals"], "rows": v["rows"], "results": v["results"], "activity": v["activity"]}
snap["seconds"] = round(time.time() - t0)
json.dump(snap, open(f"spikes/out/e2e_{scen}.json", "w"), indent=1, default=str)
print(scen, "outcome", v["plan"]["outcome"], "totals", v["totals"], "seconds", snap["seconds"])
for r in v["rows"]:
    print(f"  {r['participant'][:20]:20} qty {r['qty']:>2} held {r['hold_amount']:>6} charged {r['captured']:>6} released {r['released']:>6} {r['status']:9} {r['auth_ids']}")
bad = [a for a in v["activity"] if a["status"] >= 400]
print("  paypal errors:", bad)
