"""Wider phrasing coverage for the offline StubReader, so a live demo with ad-lib messages is less brittle.
Each case: earlier messages from the same buyer, then the new message, then that buyer's expected final order."""
import pytest

from tipping_point.chat import Message
from tipping_point.ledger import build_order_list
from tipping_point.readers import ReaderContext, StubReader

CTX = ReaderContext("Auntie Lin", ["MSW", "D24"], {"msw": "MSW", "d24": "D24", "mao shan wang": "MSW"})


def final(*texts, who="Wei"):
    msgs = [Message(i + 1, None, who, t) for i, t in enumerate(texts)]
    ol = build_order_list(StubReader().extract(msgs, CTX), CTX.variants)
    return {(l.variant, l.qty) for l in ol.lines if l.participant == who and l.qty}, {i.kind for i in ol.issues}


CASES = [
    (["2 MSW"], {("MSW", 2)}),
    (["2msw pls"], {("MSW", 2)}),
    (["MSW x2"], {("MSW", 2)}),
    (["2x MSW"], {("MSW", 2)}),
    (["two mao shan wang"], {("MSW", 2)}),
    (["count me in for 1 D24"], {("D24", 1)}),
    (["count me in! MSW"], {("MSW", 1)}),
    (["chope 3 MSW"], {("MSW", 3)}),
    (["ok im in, 2 D24"], {("D24", 2)}),
    (["2 MSW", "+1 MSW"], {("MSW", 3)}),
    (["2 MSW", "add 1 more MSW"], {("MSW", 3)}),
    (["2 MSW", "one more MSW"], {("MSW", 3)}),
    (["2 MSW", "another 2 MSW"], {("MSW", 4)}),
    (["3 MSW", "-1"], {("MSW", 2)}),
    (["3 MSW", "one less"], {("MSW", 2)}),
    (["3 MSW", "minus 1, wife say too much"], {("MSW", 2)}),
    (["3 MSW", "make it 5"], {("MSW", 5)}),
    (["3 MSW", "change to 1 MSW and 1 D24"], {("MSW", 1), ("D24", 1)}),
    (["2 MSW", "switch mine to D24"], {("D24", 2)}),
    (["2 MSW", "cancel"], set()),
    (["2 MSW", "nvm, cancel mine"], set()),
    (["2 MSW", "sorry don't want liao"], set()),
    (["2 MSW", "never mind, skip me this round"], set()),
    (["2 MSW", "scratch mine"], set()),
    (["2 MSW", "1 D24", "cancel the D24"], {("MSW", 2)}),
]


@pytest.mark.parametrize("texts,expected", CASES, ids=[" | ".join(c[0]) for c in CASES])
def test_phrasing(texts, expected):
    got, _ = final(*texts)
    assert got == expected


@pytest.mark.parametrize("text", ["maybe 2 MSW", "tbc, probably 1 D24", "let me check with wife first", "will confirm later 2 MSW",
                                  "ask my hubby first"])
def test_soft_interest_is_not_an_order(text):
    got, issues = final(text)
    assert got == set() and "MAYBE" in issues


@pytest.mark.parametrize("text", ["is D24 bitter?", "how much for 3 MSW?", "got delivery or self collect?"])
def test_questions_are_not_orders(text):
    got, issues = final(text)
    assert got == set() and "QUESTION" in issues


@pytest.mark.parametrize("text", ["wah durian 🤤", "lol", "thanks auntie!", "see you Sunday"])
def test_chatter_is_ignored(text):
    got, issues = final(text)
    assert got == set() and not issues
