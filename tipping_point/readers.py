"""Chat readers behind one interface.

`ChatReader.extract(messages, ctx) -> list[CommitmentEvent]`.

- StubReader: deterministic, rule-based, offline. Used by tests and as the no-key fallback. It is a
  stand-in, not the product's intelligence: it handles the phrasings in our fixtures plus common
  variants, and anything it does not understand is left out (never guessed).
- GeminiReader: Google Gemini via REST `generateContent` with a JSON response schema. Activated when
  a key is configured. Its output goes through the same grounding check as the stub.
"""
from __future__ import annotations

import json
import os
import time
import re
from dataclasses import dataclass, field
from typing import Protocol

import httpx

from .chat import Message
from .events import CommitmentEvent, Kind


@dataclass
class ReaderContext:
    organiser: str                       # sender name (or prefix) of the organiser
    variants: list[str] = field(default_factory=list)
    aliases: dict[str, str] = field(default_factory=dict)   # alias (lower) -> canonical variant


class ChatReader(Protocol):
    name: str

    def extract(self, messages: list[Message], ctx: ReaderContext) -> list[CommitmentEvent]: ...


def is_organiser(sender: str, ctx: ReaderContext) -> bool:
    return bool(ctx.organiser) and sender.lower().startswith(ctx.organiser.lower())


# ---------------------------------------------------------------- grounding check (all readers)

class GroundingError(ValueError):
    pass


def ground(events: list[CommitmentEvent], messages: list[Message], ctx: ReaderContext) -> list[CommitmentEvent]:
    """Drop or reject events that are not supported by the chat. Applied to every reader's output.

    - source_id must exist
    - participant must be the sender, unless the event carries added_by == sender (ordering for someone else)
    - variant must be a known variant (or None)
    - qty must be a positive int where present
    """
    by_id = {m.id: m for m in messages}
    variants = set(ctx.variants)
    ok: list[CommitmentEvent] = []
    for e in events:
        m = by_id.get(e.source_id)
        if m is None:
            raise GroundingError(f"event cites unknown message {e.source_id}")
        if e.participant != m.sender and e.added_by != m.sender:
            raise GroundingError(f"message {e.source_id} from {m.sender!r} cannot create an order for {e.participant!r}")
        if e.variant is not None and variants and e.variant not in variants:
            raise GroundingError(f"unknown variant {e.variant!r} in message {e.source_id}")
        if e.qty is not None and e.qty <= 0:
            raise GroundingError(f"non-positive qty in message {e.source_id}")
        ok.append(e)
    return ok


# ---------------------------------------------------------------- deterministic stub

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "a dozen": 12, "a pair of": 2}
_CANCEL = re.compile(r"\b(cancel|drop me|count me out|i'?m out|remove me|not joining|withdraw|nvm|never ?mind|"
                     r"don'?t want|dont need|no need (?:for me|liao)|skip me|drop out|out liao|scratch (?:mine|me)|"
                     r"remove mine|cannot make it|can'?t join|pass (?:on this|this time))\b", re.I)
_MAYBE = re.compile(r"\b(maybe|thinking about|see how|not sure|might|tbc|let me check|will confirm|confirm later|"
                    r"probably|considering|ask my (?:wife|husband|hubby|mum|mom))\b", re.I)
_COPY = re.compile(r"\bsame as ([A-Za-z][\w.]*(?: [A-Z][\w.]*)?)", re.I)
_ADD_PREFIX = re.compile(r"^\s*\+\s*(\d+)\b")
_ADD_MORE = re.compile(r"\b(?:add|another|plus)\s+(\d+|one|two|three)\b(?!\s+for\s+[A-Z])|\b(\d+|one|two|three)\s+more\b", re.I)
_JOIN = re.compile(r"\b(count me in|i'?m in|me in|chope|join(?:ing)?|me also|me too|i want|want)\b", re.I)
_MINUS_PREFIX = re.compile(r"^\s*-\s*(\d+)\b")
_ONE_LESS = re.compile(r"\b(\d+|one|two)\s+less\b", re.I)
_MINUS = re.compile(r"\b(?:minus|less|remove|reduce by)\s+(\d+)\b", re.I)
_SWITCH = re.compile(r"\b(switch|change|still|swap)\b", re.I)
_KEEP = re.compile(r"\bkeep\b", re.I)
_ON_BEHALF = re.compile(r"^\s*add\s+(.*?)\s+for\s+([A-Z][\w]*(?:\s+[A-Z][\w]*)*)", re.S)


def _split_clauses(text: str) -> list[str]:
    parts = re.split(r"\n|,|;|\band\b", text)
    return [p.strip() for p in parts if p and p.strip()]


class StubReader:
    name = "stub"

    def _variant_patterns(self, ctx: ReaderContext):
        names = {v: v for v in ctx.variants}
        names.update(ctx.aliases)
        pats = []
        for alias in sorted(names, key=len, reverse=True):
            canon = names[alias]
            flags = 0 if len(alias) <= 2 else re.I    # single/double-letter sizes are case-sensitive
            pats.append((re.compile(r"(?<![\w+])" + re.escape(alias) + r"(?![\w+])", flags), canon))
        return pats

    def _variants_in(self, s: str, pats) -> list[tuple[int, str]]:
        found, taken = [], []
        for p, canon in pats:
            for m in p.finditer(s):
                if any(a <= m.start() < b for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append((m.start(), canon))
        return sorted(found)

    def _qty_variant_pairs(self, s: str, pats) -> list[tuple[int, str | None]]:
        """Find (qty, variant) pairs like '2 x M', 'S x1', '3 pcs size L', '4 MSW', '1 base'."""
        s = re.sub(r"(?i)\bx(\d)", r"x \1", s)
        s = re.sub(r"(?i)(\d)x\b", r"\1 x", s)
        vs = self._variants_in(s, pats)
        nums = [(m.start(), int(m.group(1))) for m in re.finditer(r"(?<![\w+])(\d+)(?!\d)", s)]
        if not nums:
            nums = [(m.start(), _WORDS[m.group(1).lower()]) for m in re.finditer(r"\b(" + "|".join(_WORDS) + r")\b", s, re.I)]
        if not nums:
            return []
        if not vs:
            return [(nums[0][1], None)]
        pairs, used = [], set()
        for vpos, v in vs:
            # nearest number on either side, preferring the closest
            best = min((n for n in nums if n[0] not in used), key=lambda n: abs(n[0] - vpos), default=None)
            if best is not None:
                used.add(best[0])
                pairs.append((best[1], v))
        return pairs

    def _clause(self, c: str, sender: str, mid: int, pats, own_variant_known: bool) -> list[CommitmentEvent]:
        ev = lambda **k: CommitmentEvent(participant=sender, source_id=mid, **k)
        c = re.sub(r"(?<![A-Za-z\d])(\d+)(?!x\b)([A-Za-z])", r"\1 \2", c)   # "2msw" -> "2 msw", "3XS" -> "3 XS"; keeps "D24", "2x"
        variants = [v for _, v in self._variants_in(c, pats)]
        if _MAYBE.search(c):
            pairs = self._qty_variant_pairs(c, pats)
            return [ev(kind=Kind.MAYBE, qty=pairs[0][0] if pairs else None, variant=pairs[0][1] if pairs else None)]
        if "?" in c:
            return [ev(kind=Kind.QUESTION, note=c)]
        if _CANCEL.search(c):
            d = re.search(r"\bcancel\s+(\d+)\b", c, re.I)
            if d:
                return [ev(kind=Kind.REMOVE, qty=int(d.group(1)), variant=variants[0] if variants else None)]
            if variants:
                return [ev(kind=Kind.CANCEL, variant=v) for v in variants]
            return [ev(kind=Kind.CANCEL)]
        if _KEEP.search(c) and not re.search(r"\d", c):
            return []
        m = _COPY.search(c)
        if m:
            return [ev(kind=Kind.COPY, copy_from=m.group(1).strip())]
        m = _MINUS.search(c) or _MINUS_PREFIX.match(c) or _ONE_LESS.search(c)
        if m:
            q = m.group(1)
            q = int(q) if q.isdigit() else _WORDS[q.lower()]
            return [ev(kind=Kind.REMOVE, qty=q, variant=variants[0] if variants else None)]
        m = _ADD_PREFIX.match(c) or re.search(r"\+\s*(\d+)\s+more\b", c, re.I)
        if m:
            rest = c[m.end():]
            vs = [v for _, v in self._variants_in(rest, pats)]
            return [ev(kind=Kind.ADD, qty=int(m.group(1)), variant=vs[0] if vs else None)]
        m = _ADD_MORE.search(c)
        if m and not re.search(r"\b(?:make|change|total|to)\b", c, re.I):
            q = m.group(1) or m.group(2)
            q = int(q) if q.isdigit() else _WORDS[q.lower()]
            vs = [v for _, v in self._variants_in(c, pats)]
            return [ev(kind=Kind.ADD, qty=q, variant=vs[0] if vs else None)]
        pairs = self._qty_variant_pairs(c, pats)
        if pairs:
            return [ev(kind=Kind.SET, qty=q, variant=v) for q, v in pairs]
        if variants and _SWITCH.search(c):
            return [ev(kind=Kind.SET_VARIANT, variant=variants[0])]
        if _JOIN.search(c) or re.fullmatch(r"\s*\+\s*", c):
            # "count me in" / "me too" with no number: one unit (of the named variant if any)
            return [ev(kind=Kind.SET, qty=1, variant=variants[0] if variants else None, note="join-default")]
        return []

    def extract(self, messages: list[Message], ctx: ReaderContext) -> list[CommitmentEvent]:
        pats = self._variant_patterns(ctx)
        out: list[CommitmentEvent] = []
        for msg in messages:
            if is_organiser(msg.sender, ctx):
                for c in _split_clauses(msg.text):
                    m = _ON_BEHALF.match(c)
                    if not m:
                        continue
                    who = re.sub(r"\s*\(.*", "", m.group(2)).strip()
                    for e in self._clause(m.group(1), who, msg.id, pats, False):
                        out.append(e.model_copy(update={"added_by": msg.sender}))
                continue
            evs = [e for c in _split_clauses(msg.text) for e in self._clause(c, msg.sender, msg.id, pats, True)]
            if any(e.note != "join-default" for e in evs):   # "ok im in, 1 base": the explicit order wins
                evs = [e for e in evs if e.note != "join-default"]
            out.extend(evs)
        return ground(out, messages, ctx)


# ---------------------------------------------------------------- Gemini

_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "kind": {"type": "STRING", "enum": [k.value for k in Kind]},
            "participant": {"type": "STRING"},
            "source_id": {"type": "INTEGER"},
            "qty": {"type": "INTEGER", "nullable": True},
            "variant": {"type": "STRING", "nullable": True},
            "copy_from": {"type": "STRING", "nullable": True},
            "added_by": {"type": "STRING", "nullable": True},
            "note": {"type": "STRING", "nullable": True},
        },
        "required": ["kind", "participant", "source_id"],
    },
}

_PROMPT = """You read a group-buy chat and list every order-relevant event, in chat order.
Event kinds: SET (wants exactly qty), ADD (+qty), REMOVE (-qty), CANCEL (drops out; variant optional),
SET_VARIANT (switches existing order to a variant), COPY ("same as X": copy_from=X's sender name),
MAYBE (soft interest, not an order), QUESTION (asks something before committing).
Rules: participant is the sender, except when the organiser (or anyone) orders for a named other person:
then participant is that person and added_by is the sender. "for my mum/bro" WITHOUT a name stays the sender.
Use only these variants (canonical spelling): {variants}. If no variant is stated, leave variant null.
Ignore the organiser's announcements and answers. Ignore chatter. Never invent quantities.
source_id must be the [id] of the message the event came from.
Organiser: {organiser}
Messages:
{messages}"""


class GeminiReader:
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None, client: httpx.Client | None = None,
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta"):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-3.7-flash,gemini-3.5-flash")  # comma list: next model on 429/503
        self.models = [m.strip() for m in self.model.split(",") if m.strip()]
        self.client = client or httpx.Client(timeout=60)
        self.base_url = base_url

    def extract(self, messages: list[Message], ctx: ReaderContext) -> list[CommitmentEvent]:
        lines = "\n".join(f"[{m.id}] {m.sender}: {m.text}" for m in messages)
        prompt = _PROMPT.format(variants=", ".join(ctx.variants) or "(none)", organiser=ctx.organiser, messages=lines)
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": _SCHEMA}}
        # free tier: 429 (quota) and 503 (high demand) are common, so back off briefly, then try the next model
        for model in self.models:
            for attempt in range(2):
                r = self.client.post(f"{self.base_url}/models/{model}:generateContent",
                                     headers={"x-goog-api-key": self.api_key}, json=body)
                if r.status_code not in (429, 500, 503):
                    break
                time.sleep(2)
            if r.status_code not in (429, 500, 503):
                self.last_model = model
                break
        r.raise_for_status()
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        events = [CommitmentEvent(**e) for e in json.loads(text)]
        return ground(events, messages, ctx)


class FallbackReader:
    """Live-demo safety: use the primary (Gemini); if it errors or its answer fails grounding, use the stub
    and say so (`last_note` is shown in the UI). Never silently mixes the two within one read."""

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.last_note: str | None = None
        self.last_used: str | None = None

    def extract(self, messages: list[Message], ctx: ReaderContext) -> list[CommitmentEvent]:
        try:
            out = self.primary.extract(messages, ctx)
            self.last_note, self.last_used = None, self.primary.name
            return out
        except (GroundingError, httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            self.last_note = f"{self.primary.name} unavailable ({type(e).__name__}); used offline rules"
            self.last_used = self.fallback.name
            return self.fallback.extract(messages, ctx)


def make_reader(provider: str | None = None) -> ChatReader:
    provider = (provider or os.environ.get("TP_READER", "stub")).lower()
    if provider == "gemini":
        return FallbackReader(GeminiReader(), StubReader())
    return StubReader()
