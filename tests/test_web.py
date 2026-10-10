from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from tipping_point.demo_runner import run_buyers
from tipping_point.paypal import FakeHolds
from tipping_point.service import Service
from tipping_point.web import create_app


@pytest.fixture
def env():
    svc = Service(FakeHolds(), "http://testserver", mode="fake")
    return svc, TestClient(create_app(svc))


def start(client, sample):
    cid = client.post("/api/campaigns", json={"sample": sample}).json()["id"]
    v = client.post(f"/api/campaigns/{cid}/read").json()
    return cid, v


def buyers_return_via_http(svc, client, cid):
    """Every pending buyer approves on 'PayPal' and is redirected to our return URL."""
    for h in list(svc.campaigns[cid].holds.values()):
        if h.status == "LINK_SENT":
            svc.api.approve(h.order_id)
            r = client.get(f"/r/{cid}/{h.id}")
            assert r.status_code == 200 and "held, not charged" in r.text


def test_index_and_info(env):
    _, c = env
    assert "Tipping Point" in c.get("/").text
    assert c.get("/api/info").json() == {"mode": "fake", "reader": "stub", "samples": ["durian", "socks", "keycaps"]}


def test_socks_tips_and_captures_lower_than_hold(env):
    svc, c = env
    cid, v = start(c, "socks")
    assert v["progress"]["committed"] == 30 and v["stage"] == "read"
    assert {m["cls"] for m in v["messages"]} >= {"order", "organiser", "flag"}
    v = c.post(f"/api/campaigns/{cid}/holds").json()
    assert v["stage"] == "collecting" and all(r["status"] == "AWAITING BUYER" for r in v["rows"])
    assert v["progress"]["held"] == 0 and not v["progress"]["tipped"] or v["progress"]["counted"] == 0
    buyers_return_via_http(svc, c, cid)
    v = c.get(f"/api/campaigns/{cid}").json()
    assert v["progress"]["held"] == 30 and v["progress"]["tipped"] and v["progress"]["unit_now"] == "2.20"
    v = c.post(f"/api/campaigns/{cid}/close").json()
    plan = v["plan"]
    assert plan["outcome"] == "TIPPED" and plan["unit_price"] == "2.20" and plan["capture_total"] == "66.00"
    assert all(a["request"]["body"]["final_capture"] for a in plan["actions"] if a["kind"] == "capture")
    assert c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": "wrong"}).status_code == 409
    v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": plan["hash"]}).json()
    assert v["stage"] == "settled" and {r["status"] for r in v["rows"]} == {"CAPTURED"}
    assert v["totals"] == {"held": "75.00", "captured": "66.00", "released": "9.00"}
    ahmad = next(r for r in v["rows"] if r["participant"] == "Ahmad")
    assert (ahmad["hold_amount"], ahmad["captured"], ahmad["released"]) == ("12.50", "11.00", "1.50")
    assert any("/capture" in a["path"] for a in v["activity"])


def test_durian_misses_and_releases_everything(env):
    svc, c = env
    cid, v = start(c, "durian")
    c.post(f"/api/campaigns/{cid}/holds")
    buyers_return_via_http(svc, c, cid)
    v = c.post(f"/api/campaigns/{cid}/close").json()
    assert v["plan"]["outcome"] == "FAILED" and v["plan"]["shortfall"] == 3
    v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": v["plan"]["hash"]}).json()
    assert {r["status"] for r in v["rows"]} == {"RELEASED"} and v["totals"]["captured"] == "0.00"
    assert {a.status for a in svc.api.auths.values()} == {"VOIDED"}


def test_late_change_needs_top_up_hold(env):
    svc, c = env
    cid, _ = start(c, "socks")
    c.post(f"/api/campaigns/{cid}/holds")
    buyers_return_via_http(svc, c, cid)
    v = c.post(f"/api/campaigns/{cid}/chat", json={"text": "Grace: actually make mine 6"}).json()
    grace = next(r for r in v["rows"] if r["participant"] == "Grace")
    assert grace["qty"] == 6 and grace["status"] == "TOP-UP NEEDED"
    assert v["messages"][-1]["text"] == "actually make mine 6" and v["messages"][-1]["chips"][0]["text"] == "6"
    v = c.post(f"/api/campaigns/{cid}/holds").json()
    top = [l for l in next(r for r in v["rows"] if r["participant"] == "Grace")["links"] if l["kind"] == "top-up"]
    assert len(top) == 1 and top[0]["qty"] == 2 and top[0]["amount"] == "5.00"
    buyers_return_via_http(svc, c, cid)
    v = c.post(f"/api/campaigns/{cid}/close").json()
    caps = [a for a in v["plan"]["actions"] if a["participant"] == "Grace" and a["kind"] == "capture"]
    assert [a["amount"] for a in caps] == ["10.00", "3.20"]        # 6 x 2.20 split across the two holds
    v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": v["plan"]["hash"]}).json()
    assert v["totals"]["captured"] == "70.40"                        # 32 pairs x 2.20


def test_reduced_qty_needs_no_new_hold(env):
    svc, c = env
    cid, _ = start(c, "socks")
    c.post(f"/api/campaigns/{cid}/holds"); buyers_return_via_http(svc, c, cid)
    v = c.post(f"/api/campaigns/{cid}/chat", json={"text": "Ahmad: minus 1"}).json()
    assert next(r for r in v["rows"] if r["participant"] == "Ahmad")["status"] == "HELD"
    assert c.post(f"/api/campaigns/{cid}/holds").json()["rows"] == v["rows"]   # nothing new to send


def test_buyer_who_never_approves_is_not_counted(env):
    svc, c = env
    cid, _ = start(c, "socks")
    c.post(f"/api/campaigns/{cid}/holds")
    run_buyers(svc, cid, pace_s=0, skip={"Ahmad"})
    v = c.post(f"/api/campaigns/{cid}/close").json()
    assert v["plan"]["total_qty"] == 25 and v["plan"]["outcome"] == "TIPPED" and v["plan"]["unit_price"] == "2.50"
    v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": v["plan"]["hash"]}).json()
    assert next(r for r in v["rows"] if r["participant"] == "Ahmad")["status"] == "NOT HELD"


def test_cancel_return_and_idempotent_return(env):
    svc, c = env
    cid, _ = start(c, "keycaps")
    c.post(f"/api/campaigns/{cid}/holds")
    hs = list(svc.campaigns[cid].holds.values())
    assert "Nothing was held" in c.get(f"/x/{cid}/{hs[0].id}").text
    svc.api.approve(hs[1].order_id)
    c.get(f"/r/{cid}/{hs[1].id}"); c.get(f"/r/{cid}/{hs[1].id}")
    assert len(svc.api.auths) == 1


def test_sync_picks_up_approval_without_return(env):
    svc, c = env
    cid, _ = start(c, "keycaps")
    c.post(f"/api/campaigns/{cid}/holds")
    h = next(iter(svc.campaigns[cid].holds.values()))
    svc.api.approve(h.order_id)          # buyer approved but closed the tab before the redirect
    c.post(f"/api/campaigns/{cid}/sync")
    assert h.status == "HELD"


def test_webhook_requires_verification(env, monkeypatch):
    svc, c = env
    cid, _ = start(c, "keycaps")
    c.post(f"/api/campaigns/{cid}/holds")
    h = next(iter(svc.campaigns[cid].holds.values()))
    svc.api.approve(h.order_id)
    ev = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": h.order_id}}
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID", raising=False)
    assert c.post("/api/webhooks/paypal", json=ev).status_code == 400
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    assert c.post("/api/webhooks/paypal", json=ev, headers={"paypal-transmission-sig": "forged"}).status_code == 400
    r = c.post("/api/webhooks/paypal", json=ev, headers={"paypal-transmission-sig": "fake-valid"})
    assert r.json() == {"result": "authorized"} and h.status == "HELD"


def test_closed_campaign_rejects_changes(env):
    svc, c = env
    cid, _ = start(c, "keycaps")
    c.post(f"/api/campaigns/{cid}/holds"); c.post(f"/api/campaigns/{cid}/close")
    assert c.post(f"/api/campaigns/{cid}/chat", json={"text": "kai: +5 base"}).status_code == 409
    assert c.post(f"/api/campaigns/{cid}/holds").status_code == 409


def test_append_chat_keeps_export_format(env):
    svc, c = env
    for sample, who in (("durian", "Priya"), ("socks", "Clara"), ("keycaps", "Esther")):
        cid, v0 = start(c, sample)
        v = c.post(f"/api/campaigns/{cid}/chat", json={"text": f"{who}: 2"}).json()
        assert len(v["messages"]) == len(v0["messages"]) + 1 and v["messages"][-1]["sender"] == who


def test_edited_paste_uses_sample_settings(env):
    _, c = env
    r = c.post("/api/campaigns", json={"sample": "durian", "chat_text": "10/10/26, 20:04 - Bo: 25 MSW\n"}).json()
    v = c.post(f"/api/campaigns/{r['id']}/read").json()
    assert v["progress"]["committed"] == 25 and v["campaign"]["moq"] == 20


def test_failed_paypal_call_keeps_campaign_open_and_retry_is_safe(env):
    svc, c = env
    cid, _ = start(c, "socks")
    c.post(f"/api/campaigns/{cid}/holds"); buyers_return_via_http(svc, c, cid)
    v = c.post(f"/api/campaigns/{cid}/close").json()
    grace_auth = next(a["auth"] for a in v["plan"]["actions"] if a["participant"] == "Grace")
    svc.api.fail_once.add(grace_auth)
    v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": v["plan"]["hash"]}).json()
    assert v["stage"] == "closed" and v["settle_errors"] == [{"participant": "Grace", "action": "capture", "issue": "SERVICE_UNAVAILABLE"}]
    assert next(r for r in v["rows"] if r["participant"] == "Grace")["status"] == "PAYPAL ERROR"
    captured_before = sum(a.captured for a in svc.api.auths.values())
    v = c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": v["plan"]["hash"]}).json()
    assert v["stage"] == "settled" and v["totals"]["captured"] == "66.00"
    assert sum(a.captured for a in svc.api.auths.values()) == captured_before + D("8.80")   # only Grace's capture ran again


def test_demo_progress_reported(env):
    svc, c = env
    cid, _ = start(c, "keycaps")
    c.post(f"/api/campaigns/{cid}/holds")
    run_buyers(svc, cid, pace_s=0)
    v = c.get(f"/api/campaigns/{cid}").json()
    assert v["demo_progress"] == {"done": 7, "total": 7, "current": None} and len(v["demo_log"]) == 7


def test_settle_before_close_is_rejected(env):
    svc, c = env
    cid, _ = start(c, "keycaps")
    assert c.post(f"/api/campaigns/{cid}/settle", json={"plan_hash": "x"}).status_code == 409
