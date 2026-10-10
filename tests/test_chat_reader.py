import json
from pathlib import Path

import httpx
import pytest

from tipping_point.chat import parse_export, parse_telegram, parse_whatsapp
from tipping_point.events import CommitmentEvent, Kind
from tipping_point.ledger import build_order_list
from tipping_point.readers import GeminiReader, GroundingError, ReaderContext, StubReader, ground, make_reader

FX = Path(__file__).parent.parent / "fixtures"
EXPECTED = json.loads((FX / "expected.json").read_text())


def ctx_of(d):
    return ReaderContext(d["organiser"], d["variants"], d["aliases"])


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fixture_order_lists(name):
    exp = EXPECTED[name]
    msgs = parse_export((FX / name).read_text())
    ctx = ctx_of(exp["ctx"])
    ol = build_order_list(StubReader().extract(msgs, ctx), ctx.variants)
    assert [[r["participant"], r["variant"], r["qty"]] for r in ol.as_rows()] == exp["rows"]
    assert ol.total == exp["total"]
    assert sorted([i.kind, i.participant] for i in ol.issues) == sorted(exp["issues"])
    for i in ol.issues:
        assert i.draft_reply


def test_fixtures_feed_settlement():
    """End to end on the fixtures: durian and keycaps miss MOQ, uniforms tip exactly."""
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal as D
    from tipping_point.campaign import Campaign, Hold, Outcome, Tier, hold_amount, plan_settlement
    t0 = datetime(2026, 10, 10, tzinfo=timezone.utc)
    outcomes = {}
    for name, exp in EXPECTED.items():
        ctx = ctx_of(exp["ctx"])
        ol = build_order_list(StubReader().extract(parse_export((FX / name).read_text()), ctx), ctx.variants)
        c = Campaign(name, name, "SGD", exp["campaign"]["moq"], [Tier(a, D(b)) for a, b in exp["campaign"]["tiers"]],
                     t0, t0 + timedelta(hours=48))
        q = ol.by_participant()
        h = {p: [Hold(p, f"A-{p}", hold_amount(c, n), t0)] for p, n in q.items()}
        outcomes[name] = plan_settlement(c, q, h, now=c.deadline).outcome
    assert outcomes == {"durian_tampines_whatsapp_android.txt": Outcome.FAILED,
                        "house_socks_whatsapp_ios.txt": Outcome.TIPPED,
                        "keycaps_telegram_export.json": Outcome.FAILED}


def test_whatsapp_multiline_and_system_lines():
    msgs = parse_whatsapp((FX / "durian_tampines_whatsapp_android.txt").read_text())
    assert not any("encrypted" in m.text for m in msgs)
    hui = next(m for m in msgs if m.sender == "Hui Min")
    assert hui.text == "+2 msw\nand 1 d24 for my mum"


def test_ios_timestamps_parsed():
    msgs = parse_whatsapp((FX / "house_socks_whatsapp_ios.txt").read_text())
    assert msgs[0].ts.hour == 9 and msgs[-1].ts.hour == 14


def test_telegram_rich_text_and_service_messages():
    msgs = parse_telegram((FX / "keycaps_telegram_export.json").read_text())
    assert any(m.sender == "Bryan" and m.text == "3 base please" for m in msgs)
    assert all(m.sender for m in msgs)


@pytest.mark.parametrize("text,kind,qty,variant", [
    ("+1 MSW", Kind.ADD, 1, "MSW"),
    ("me 2 boxes d24 pls", Kind.SET, 2, "D24"),
    ("M x2", Kind.SET, 2, "M"),
    ("2x M", Kind.SET, 2, "M"),
    ("maybe 3", Kind.MAYBE, 3, None),
    ("cancel mine", Kind.CANCEL, None, None),
    ("minus 2", Kind.REMOVE, 2, None),
    ("is it halal?", Kind.QUESTION, None, None),
    ("switch to D24", Kind.SET_VARIANT, None, "D24"),
    ("two MSW", Kind.SET, 2, "MSW"),
])
def test_stub_phrasings(text, kind, qty, variant):
    from tipping_point.chat import Message
    ctx = ReaderContext("Org", ["MSW", "D24", "M"], {"msw": "MSW", "d24": "D24"})
    ev = StubReader().extract([Message(1, None, "Ann", text)], ctx)
    assert len(ev) == 1 and (ev[0].kind, ev[0].qty, ev[0].variant) == (kind, qty, variant)


def test_stub_ignores_chatter_and_organiser_announcements():
    from tipping_point.chat import Message
    ctx = ReaderContext("Org", ["MSW"])
    msgs = [Message(1, None, "Org (host)", "Need 20 boxes, 30+ cheaper"), Message(2, None, "Bo", "wah shiok 🤤")]
    assert StubReader().extract(msgs, ctx) == []


# ---- grounding: an LLM cannot invent orders
def _msgs():
    from tipping_point.chat import Message
    return [Message(1, None, "Ann", "2 MSW"), Message(2, None, "Org (host)", "add 1 MSW for Bob")]


@pytest.mark.parametrize("bad", [
    dict(kind="SET", participant="Ann", source_id=99, qty=2, variant="MSW"),        # unknown message
    dict(kind="SET", participant="Zed", source_id=1, qty=2, variant="MSW"),         # not the sender
    dict(kind="SET", participant="Ann", source_id=1, qty=2, variant="Musang"),      # unknown variant
    dict(kind="SET", participant="Ann", source_id=1, qty=0, variant="MSW"),         # non-positive
])
def test_grounding_rejects(bad):
    with pytest.raises(GroundingError):
        ground([CommitmentEvent(**bad)], _msgs(), ReaderContext("Org", ["MSW"]))


def test_grounding_allows_on_behalf():
    e = CommitmentEvent(kind="SET", participant="Bob", source_id=2, qty=1, variant="MSW", added_by="Org (host)")
    assert ground([e], _msgs(), ReaderContext("Org", ["MSW"])) == [e]


# ---- Gemini provider (no network: mocked transport)
def test_gemini_reader_request_and_parse():
    seen = {}
    out = [{"kind": "SET", "participant": "Ann", "source_id": 1, "qty": 2, "variant": "MSW"},
           {"kind": "SET", "participant": "Bob", "source_id": 2, "qty": 1, "variant": "MSW", "added_by": "Org (host)"}]

    def handler(req: httpx.Request):
        seen["url"] = str(req.url); seen["key"] = req.headers.get("x-goog-api-key")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]})

    r = GeminiReader(api_key="TEST-KEY", model="gemini-test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    ev = r.extract(_msgs(), ReaderContext("Org", ["MSW"]))
    assert [e.participant for e in ev] == ["Ann", "Bob"]
    assert seen["url"].endswith("/models/gemini-test:generateContent") and seen["key"] == "TEST-KEY"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "[1] Ann: 2 MSW" in seen["body"]["contents"][0]["parts"][0]["text"]


def test_gemini_hallucination_is_rejected():
    bad = [{"kind": "SET", "participant": "Ghost", "source_id": 1, "qty": 9, "variant": "MSW"}]
    h = lambda req: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(bad)}]}}]})
    r = GeminiReader(api_key="k", client=httpx.Client(transport=httpx.MockTransport(h)))
    with pytest.raises(GroundingError):
        r.extract(_msgs(), ReaderContext("Org", ["MSW"]))


def test_make_reader_defaults_to_stub(monkeypatch):
    monkeypatch.delenv("TP_READER", raising=False)
    assert make_reader().name == "stub"
    monkeypatch.setenv("TP_READER", "gemini"); monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        make_reader()


def test_fallback_reader_uses_stub_when_gemini_answer_fails_grounding():
    from tipping_point.readers import FallbackReader
    import json as _j
    bad = [{"kind": "SET", "participant": "Ghost", "source_id": 1, "qty": 2}]
    def handler(req):
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": _j.dumps(bad)}]}}]})
    g = GeminiReader(api_key="test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = FallbackReader(g, StubReader())
    msgs = parse_whatsapp("10/10/26, 20:04 - Jason Tan: 2 MSW\n")
    ctx = ReaderContext("Auntie Lin", ["MSW", "D24"], {})
    ev = r.extract(msgs, ctx)
    assert [(e.participant, e.qty, e.variant) for e in ev] == [("Jason Tan", 2, "MSW")]
    assert r.last_used == "stub" and "GroundingError" in r.last_note


def test_fallback_reader_on_http_error():
    from tipping_point.readers import FallbackReader
    g = GeminiReader(api_key="test", client=httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(429, json={}))))
    r = FallbackReader(g, StubReader())
    ev = r.extract(parse_whatsapp("10/10/26, 20:04 - Jason Tan: 2 MSW\n"), ReaderContext("x", ["MSW"], {}))
    assert ev and r.last_used == "stub" and "HTTPStatusError" in r.last_note


def test_grounding_accepts_sender_name_without_parenthetical():
    from tipping_point.chat import Message
    from tipping_point.events import CommitmentEvent, Kind
    from tipping_point.readers import ReaderContext, ground, GroundingError
    import pytest
    msgs = [Message(id=1, sender="Auntie Lin (organiser)", text="add 2 MSW for Uncle Boon", ts=None)]
    ctx = ReaderContext("Auntie Lin", ["MSW"], {})
    out = ground([CommitmentEvent(participant="Uncle Boon", added_by="Auntie Lin", source_id=1, kind=Kind.SET, qty=2, variant="MSW")], msgs, ctx)
    assert out[0].added_by == "Auntie Lin (organiser)"
    with pytest.raises(GroundingError):   # a different person is still rejected
        ground([CommitmentEvent(participant="Uncle Boon", added_by="Kelvin", source_id=1, kind=Kind.SET, qty=2, variant="MSW")], msgs, ctx)
