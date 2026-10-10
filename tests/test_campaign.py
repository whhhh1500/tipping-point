from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

from tipping_point.campaign import Campaign, Hold, Outcome, RuleError, Tier, hold_amount, plan_settlement

T0 = datetime(2026, 10, 10, 20, 0, tzinfo=timezone.utc)


def camp(**kw):
    base = dict(id="c1", item="TEST durian 1kg", currency="SGD", moq=20,
                tiers=[Tier(20, D("38.00")), Tier(30, D("34.00")), Tier(40, D("30.00"))],
                opens_at=T0, deadline=T0 + timedelta(hours=48))
    base.update(kw)
    return Campaign(**base)


def holds_for(c, qtys, at=T0 + timedelta(hours=1)):
    return {p: [Hold(p, f"AUTH-{p}", hold_amount(c, q), at)] for p, q in qtys.items()}


# ---- validation
@pytest.mark.parametrize("kw,msg", [
    (dict(deadline=T0 + timedelta(hours=72)), "72 hours"),
    (dict(deadline=T0 + timedelta(hours=80)), "72 hours"),
    (dict(deadline=T0 - timedelta(hours=1)), "after opening"),
    (dict(moq=0), "MOQ"),
    (dict(tiers=[]), "tier"),
    (dict(tiers=[Tier(25, D("38"))]), "at or below the MOQ"),
    (dict(tiers=[Tier(20, D("30")), Tier(30, D("34"))]), "must not rise"),
    (dict(tiers=[Tier(20, D("30")), Tier(20, D("28"))]), "duplicate"),
    (dict(tiers=[Tier(20, D("0"))]), "positive"),
    (dict(tiers=[Tier(20, D("1.005"))]), "decimal places"),
    (dict(opens_at=datetime(2026, 10, 10)), "timezone"),
])
def test_invalid_campaigns(kw, msg):
    with pytest.raises(RuleError, match=msg):
        camp(**kw)


def test_deadline_just_under_72h_ok():
    camp(deadline=T0 + timedelta(hours=71, minutes=59))


def test_tier_lookup_and_hold_price():
    c = camp()
    assert c.hold_unit_price == D("38.00")
    assert [c.price_for_total(n) for n in (5, 20, 29, 30, 39, 40, 100)] == [D("38.00")] * 3 + [D("34.00")] * 2 + [D("30.00")] * 2
    assert c.next_tier(25).min_qty == 30 and c.next_tier(40) is None
    assert hold_amount(c, 3) == D("114.00")


def test_max_per_person():
    c = camp(max_per_person=5)
    with pytest.raises(RuleError):
        hold_amount(c, 6)


# ---- settlement
def test_open_before_deadline():
    c = camp()
    p = plan_settlement(c, {"a": 25}, holds_for(c, {"a": 25}), now=c.deadline - timedelta(seconds=1))
    assert p.outcome is Outcome.OPEN and p.actions == []


def test_failed_voids_every_hold():
    c = camp()
    q = {"a": 5, "b": 7, "c": 5}
    p = plan_settlement(c, q, holds_for(c, q), now=c.deadline)
    assert p.outcome is Outcome.FAILED and p.shortfall == 3
    assert sorted(a.authorization_id for a in p.actions if a.kind == "void") == ["AUTH-a", "AUTH-b", "AUTH-c"]
    assert p.capture_total == D("0.00")


def test_tipped_captures_lower_tier_price():
    c = camp()
    q = {"a": 10, "b": 12, "c": 10}           # total 32 -> $34 tier
    p = plan_settlement(c, q, holds_for(c, q), now=c.deadline)
    assert p.outcome is Outcome.TIPPED and p.unit_price == D("34.00")
    caps = {a.participant: a.amount for a in p.actions if a.kind == "capture"}
    assert caps == {"a": D("340.00"), "b": D("408.00"), "c": D("340.00")}
    # every capture is at or below its hold (the property PayPal enforces)
    for a in p.actions:
        if a.kind == "capture":
            assert a.amount <= hold_amount(c, q[a.participant])
    req = next(a for a in p.actions if a.kind == "capture").paypal_request("SGD")
    assert req["body"]["final_capture"] is True and req["path"].endswith("/capture")


def test_exact_moq_tips_at_top_price():
    c = camp()
    q = {"a": 20}
    p = plan_settlement(c, q, holds_for(c, q), now=c.deadline)
    assert p.outcome is Outcome.TIPPED and p.capture_total == D("760.00")


def test_uncovered_remainder_not_counted_and_flagged():
    c = camp()
    q = {"a": 14, "b": 7}                     # b raised qty to 7 but only holds 5 (no top-up)
    h = holds_for(c, {"a": 14, "b": 5})
    p = plan_settlement(c, q, h, now=c.deadline)
    assert p.outcome is Outcome.FAILED and p.total_qty == 19        # 14 + the 5 b actually held
    assert any(f.participant == "b" and "2 not counted" in f.reason for f in p.flags)
    q2 = {"a": 15, "b": 7}
    p2 = plan_settlement(c, q2, holds_for(c, {"a": 15, "b": 5}), now=c.deadline)
    assert p2.outcome is Outcome.TIPPED
    assert [a.amount for a in p2.actions if a.kind == "capture" and a.participant == "b"] == [D("190.00")]


def test_topup_hold_spans_two_authorizations():
    c = camp()
    q = {"a": 18, "b": 3}
    h = holds_for(c, {"a": 18, "b": 2})
    h["b"].append(Hold("b", "AUTH-b-topup", hold_amount(c, 1), T0 + timedelta(hours=5)))
    p = plan_settlement(c, q, h, now=c.deadline)
    assert p.outcome is Outcome.TIPPED and p.unit_price == D("38.00")
    b = [a for a in p.actions if a.participant == "b"]
    assert [(a.kind, a.authorization_id, a.amount) for a in b] == [
        ("capture", "AUTH-b", D("76.00")), ("capture", "AUTH-b-topup", D("38.00"))]


def test_surplus_hold_voided_when_qty_drops_to_zero():
    c = camp()
    q = {"a": 20, "b": 0}
    p = plan_settlement(c, q, holds_for(c, {"a": 20, "b": 1}), now=c.deadline)
    assert ("void", "AUTH-b") in [(a.kind, a.authorization_id) for a in p.actions]


def test_hold_past_honor_period_flagged():
    c = camp()
    q = {"a": 20}
    h = holds_for(c, q, at=T0 - timedelta(days=4))
    p = plan_settlement(c, q, h, now=c.deadline)
    assert any("honor period" in f.reason for f in p.flags)


def test_already_voided_holds_ignored():
    c = camp()
    h = {"a": [Hold("a", "AUTH-a", hold_amount(c, 20), T0, status="VOIDED")]}
    p = plan_settlement(c, {"a": 20}, h, now=c.deadline)
    assert p.outcome is Outcome.FAILED and not [a for a in p.actions if a.kind == "void"]


@pytest.mark.parametrize("seed", range(40))
def test_property_capture_never_exceeds_holds(seed):
    import random
    r = random.Random(seed)
    c = camp()
    q = {f"p{i}": r.randint(1, 6) for i in range(r.randint(1, 12))}
    p = plan_settlement(c, q, holds_for(c, q), now=c.deadline)
    held = {f"AUTH-{k}": hold_amount(c, v) for k, v in q.items()}
    for a in p.actions:
        if a.kind == "capture":
            assert a.amount <= held[a.authorization_id]
    if sum(q.values()) >= c.moq:
        assert p.capture_total == c.price_for_total(sum(q.values())) * sum(q.values())
    else:
        assert p.capture_total == 0
