import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import httpx
import pytest

from tipping_point.campaign import Campaign, Hold, Outcome, Tier, hold_amount, plan_settlement
from tipping_point.paypal import FakeHolds, PayPalError, SandboxHolds
from tipping_point.settle import ApprovalError, execute, plan_hash

T0 = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)


def camp():
    return Campaign("c1", "TEST", "SGD", 20, [Tier(20, D("38.00")), Tier(30, D("34.00"))], T0, T0 + timedelta(hours=48))


def held(api, c, qtys):
    out = {}
    for p, q in qtys.items():
        o = api.create_hold_order(f"TEST-{p}", hold_amount(c, q), "SGD", "https://example.com/r", "https://example.com/c", "TEST")
        api.approve(o["order_id"])
        a = api.authorize(o["order_id"])
        out[p] = [Hold(p, a["authorization_id"], a["amount"], T0)]
    return out


def test_fake_matches_sandbox_semantics():
    api = FakeHolds(now=lambda: T0)
    o = api.create_hold_order("r", D("30.00"), "SGD", "u", "u", "d")
    with pytest.raises(PayPalError, match="ORDER_NOT_APPROVED"):
        api.authorize(o["order_id"])
    api.approve(o["order_id"]); a = api.authorize(o["order_id"])["authorization_id"]
    with pytest.raises(PayPalError, match="REAUTHORIZATION_TOO_SOON"):
        api.reauthorize(a)
    assert api.capture(a, D("24.00"), "SGD", final=True)["status"] == "COMPLETED"
    assert api.get_authorization(a)["status"] == "CAPTURED"
    with pytest.raises(PayPalError, match="ALREADY_CAPTURED"):
        api.capture(a, D("1.00"), "SGD")
    o2 = api.create_hold_order("r2", D("30.00"), "SGD", "u", "u", "d"); api.approve(o2["order_id"])
    a2 = api.authorize(o2["order_id"])["authorization_id"]
    assert api.void(a2)["status"] == "VOIDED"
    with pytest.raises(PayPalError, match="VOIDED"):
        api.capture(a2, D("1.00"), "SGD")


def test_execute_tipped_plan_with_fake():
    api, c = FakeHolds(now=lambda: T0), camp()
    q = {"a": 15, "b": 16}
    plan = plan_settlement(c, q, held(api, c, q), now=c.deadline)
    assert plan.outcome is Outcome.TIPPED
    res = execute(plan, "SGD", plan_hash(plan, "SGD"), api, "c1")
    assert all(r["ok"] for r in res)
    assert {api.get_authorization(h)["status"] for h in api.auths} == {"CAPTURED"}
    assert sum(a.captured for a in api.auths.values()) == D("34.00") * 31


def test_execute_failed_plan_voids_all():
    api, c = FakeHolds(now=lambda: T0), camp()
    q = {"a": 5, "b": 6}
    plan = plan_settlement(c, q, held(api, c, q), now=c.deadline)
    execute(plan, "SGD", plan_hash(plan, "SGD"), api, "c1")
    assert {a.status for a in api.auths.values()} == {"VOIDED"}


def test_execute_refuses_unapproved_or_changed_plan():
    api, c = FakeHolds(now=lambda: T0), camp()
    q = {"a": 20}
    plan = plan_settlement(c, q, held(api, c, q), now=c.deadline)
    h = plan_hash(plan, "SGD")
    with pytest.raises(ApprovalError):
        execute(plan, "SGD", "nope", api, "c1")
    plan.actions[0] = plan.actions[0].__class__("capture", "a", plan.actions[0].authorization_id, D("1.00"), "tampered")
    with pytest.raises(ApprovalError):
        execute(plan, "SGD", h, api, "c1")


def test_execute_is_idempotent_on_retry():
    api, c = FakeHolds(now=lambda: T0), camp()
    q = {"a": 20}
    plan = plan_settlement(c, q, held(api, c, q), now=c.deadline)
    h = plan_hash(plan, "SGD")
    r1 = execute(plan, "SGD", h, api, "c1"); r2 = execute(plan, "SGD", h, api, "c1")
    assert r1[0]["ok"] and r2[0]["ok"] and r1[0]["result"] == r2[0]["result"]


def test_sandbox_adapter_refuses_live_url():
    with pytest.raises(ValueError):
        SandboxHolds("id", "secret", base_url="https://api-m.paypal.com")


def test_sandbox_adapter_requests_via_mock_transport():
    calls = []

    def h(req: httpx.Request):
        if req.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        calls.append((req.method, req.url.path, json.loads(req.content) if req.content else None, req.headers.get("paypal-request-id")))
        if req.url.path.endswith("/capture"):
            return httpx.Response(201, json={"id": "CAP1", "status": "COMPLETED", "amount": {"value": "24.00", "currency_code": "SGD"}})
        if req.url.path.endswith("/void"):
            return httpx.Response(204)
        if req.method == "GET":
            return httpx.Response(200, json={"id": "A1", "status": "VOIDED", "amount": {"value": "30.00", "currency_code": "SGD"}})
        return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "AUTHORIZATION_ALREADY_CAPTURED"}]})

    api = SandboxHolds("id", "secret", transport=httpx.MockTransport(h))
    assert api.capture("A1", D("24.00"), "SGD", final=True, request_id="rid-1")["amount"] == D("24.00")
    method, path, body, rid = calls[-1]
    assert path == "/v2/payments/authorizations/A1/capture" and body["final_capture"] is True and rid == "rid-1"
    assert api.void("A1")["status"] == "VOIDED"
    with pytest.raises(PayPalError, match="ALREADY_CAPTURED"):
        api._call("POST", "/v2/payments/authorizations/A1/reauthorize", {})


@pytest.mark.sandbox
@pytest.mark.skipif(os.environ.get("RUN_SANDBOX_TESTS") != "1", reason="opt-in: RUN_SANDBOX_TESTS=1")
def test_real_sandbox_partial_capture_and_void():
    """Real sandbox: tiny TEST holds, automated buyer approval, capture lower + void."""
    from playwright.sync_api import sync_playwright
    import spikes.sandbox_spike as S
    api = SandboxHolds.from_env_file()
    with sync_playwright() as p:
        page = p.chromium.launch(channel="chrome", headless=True).new_context(locale="en-US").new_page()
        o = api.create_hold_order("TEST-TP-PYTEST", D("10.00"), "SGD", S.RETURN, S.CANCEL, "TEST ONLY")
        assert S.approve(o["approve_url"], page)
        a = api.authorize(o["order_id"])
        assert api.capture(a["authorization_id"], D("8.00"), "SGD", final=True)["amount"] == D("8.00")
        assert api.get_authorization(a["authorization_id"])["status"] == "CAPTURED"
        o2 = api.create_hold_order("TEST-TP-PYTEST-V", D("10.00"), "SGD", S.RETURN, S.CANCEL, "TEST ONLY")
        assert S.approve(o2["approve_url"], page)
        a2 = api.authorize(o2["order_id"])
        assert api.void(a2["authorization_id"])["status"] == "VOIDED"
