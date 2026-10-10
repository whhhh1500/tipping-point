"""Fold commitment events into an order list. Deterministic.

The ledger never guesses: anything ambiguous becomes an Issue with a drafted clarifying reply the
organiser can paste into the group.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .events import CommitmentEvent, Kind


@dataclass
class Line:
    participant: str
    variant: str | None
    qty: int
    sources: list[int] = field(default_factory=list)
    added_by: str | None = None


@dataclass
class Issue:
    kind: str            # VARIANT_MISSING | MAYBE | QUESTION | COPY_UNKNOWN | REMOVE_TOO_MANY | ON_BEHALF | OVER_MAX
    participant: str
    source_id: int
    detail: str
    draft_reply: str


@dataclass
class OrderList:
    lines: list[Line]
    issues: list[Issue]

    @property
    def total(self) -> int:
        return sum(l.qty for l in self.lines)

    def by_variant(self) -> dict[str | None, int]:
        out: dict[str | None, int] = {}
        for l in self.lines:
            out[l.variant] = out.get(l.variant, 0) + l.qty
        return out

    def by_participant(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for l in self.lines:
            out[l.participant] = out.get(l.participant, 0) + l.qty
        return out

    def as_rows(self) -> list[dict]:
        return sorted(({"participant": l.participant, "variant": l.variant, "qty": l.qty} for l in self.lines),
                      key=lambda r: (r["participant"], r["variant"] or ""))


def _first(name: str) -> str:
    return name.split(" (")[0].split()[0] if name else name


def build_order_list(events: list[CommitmentEvent], variants: list[str] | None = None,
                     max_per_person: int | None = None) -> OrderList:
    lines: dict[tuple[str, str | None], Line] = {}
    issues: list[Issue] = []
    maybes: dict[str, Issue] = {}
    needs_variant = bool(variants)

    def mine(p):
        return [l for (pp, _), l in lines.items() if pp == p]

    def resolve_variant(e: CommitmentEvent) -> str | None:
        if e.variant or not needs_variant:
            return e.variant
        own = mine(e.participant)
        if len(own) == 1:
            return own[0].variant
        return None

    def put(p, v, qty, src, added_by=None):
        key = (p, v)
        if qty <= 0:
            lines.pop(key, None)
            return
        l = lines.get(key) or Line(p, v, 0, [], added_by)
        l.qty = qty
        l.sources.append(src)
        lines[key] = l

    for e in events:
        p = e.participant
        if e.kind in (Kind.SET, Kind.ADD, Kind.REMOVE, Kind.CANCEL, Kind.COPY, Kind.SET_VARIANT):
            maybes.pop(p, None)   # a firm action supersedes earlier "maybe"
        if e.kind is Kind.MAYBE:
            if not mine(p):
                q = f"{e.qty} " if e.qty else ""
                maybes[p] = Issue("MAYBE", p, e.source_id, f"said maybe {q}".strip(),
                                  f"Hi {_first(p)}, shall I put you down for {q or 'some '}firm? We lock holds at the deadline.")
            continue
        if e.kind is Kind.QUESTION:
            issues.append(Issue("QUESTION", p, e.source_id, e.note or "", f"(answer {_first(p)}'s question)"))
            continue
        if e.kind is Kind.CANCEL:
            for l in list(mine(p)):
                if e.variant is None or l.variant == e.variant:
                    lines.pop((p, l.variant), None)
            continue
        if e.kind is Kind.COPY:
            src = [l for (pp, _), l in lines.items() if pp.lower().startswith((e.copy_from or "").lower())]
            if not src:
                issues.append(Issue("COPY_UNKNOWN", p, e.source_id, f"same as {e.copy_from}, who has no order",
                                    f"Hi {_first(p)}, {e.copy_from} has no order yet. What would you like?"))
                continue
            for l in src:
                put(p, l.variant, l.qty, e.source_id)
            continue
        if e.kind is Kind.SET_VARIANT:
            own = mine(p)
            if len(own) == 1 and own[0].variant != e.variant:
                l = lines.pop((p, own[0].variant))
                put(p, e.variant, l.qty, e.source_id, l.added_by)
            continue
        v = resolve_variant(e)
        if needs_variant and v is None:
            issues.append(Issue("VARIANT_MISSING", p, e.source_id, f"{e.kind.value} {e.qty} without a variant",
                                f"Hi {_first(p)}, which one for your {e.qty}? Options: {', '.join(variants)}"))
            continue
        cur = lines.get((p, v)).qty if (p, v) in lines else 0
        if e.kind is Kind.SET:
            put(p, v, e.qty, e.source_id, e.added_by)
        elif e.kind is Kind.ADD:
            put(p, v, cur + e.qty, e.source_id, e.added_by)
        elif e.kind is Kind.REMOVE:
            if e.qty > cur:
                issues.append(Issue("REMOVE_TOO_MANY", p, e.source_id, f"remove {e.qty} but has {cur}",
                                    f"Hi {_first(p)}, you have {cur}; remove all?"))
            put(p, v, max(cur - e.qty, 0), e.source_id)

    for l in lines.values():
        if l.added_by:
            issues.append(Issue("ON_BEHALF", l.participant, l.sources[0], f"added by {l.added_by}",
                                f"{_first(l.added_by)}, please forward {l.participant}'s hold link to them (or pay on their behalf)."))
    if max_per_person:
        totals: dict[str, int] = {}
        for l in lines.values():
            totals[l.participant] = totals.get(l.participant, 0) + l.qty
        for p, q in totals.items():
            if q > max_per_person:
                issues.append(Issue("OVER_MAX", p, 0, f"{q} > max {max_per_person}",
                                    f"Hi {_first(p)}, max is {max_per_person} each this round."))
    issues.extend(maybes.values())
    ordered = {l.participant for l in lines.values()}
    # a question is settled once the asker went on to order
    issues = [i for i in issues if not (i.kind == "QUESTION" and i.participant in ordered)]
    return OrderList(list(lines.values()), issues)
