"""Campaign rules engine. Deterministic; the LLM never touches money.

A campaign has a supplier minimum order quantity (MOQ), volume price tiers and a deadline that must be
under 72 hours after opening, so every hold is settled inside PayPal's 3-day authorization honor period.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

MAX_CAMPAIGN = timedelta(hours=72)
CENT = Decimal("0.01")


class RuleError(ValueError):
    pass


def money(x) -> Decimal:
    d = Decimal(str(x))
    if d != d.quantize(CENT):
        raise RuleError(f"amount {x} has more than 2 decimal places")
    return d.quantize(CENT)


@dataclass(frozen=True)
class Tier:
    min_qty: int          # tier applies when the campaign total is >= min_qty
    unit_price: Decimal


@dataclass
class Campaign:
    id: str
    item: str
    currency: str
    moq: int
    tiers: list[Tier]
    opens_at: datetime
    deadline: datetime
    variants: list[str] = field(default_factory=list)
    max_per_person: int | None = None

    def __post_init__(self):
        self.tiers = sorted((Tier(int(t.min_qty), money(t.unit_price)) for t in self.tiers), key=lambda t: t.min_qty)
        self.validate()

    def validate(self):
        if self.moq < 1:
            raise RuleError("MOQ must be at least 1")
        if not self.tiers:
            raise RuleError("at least one price tier is required")
        if self.tiers[0].min_qty > self.moq:
            raise RuleError("the first tier must start at or below the MOQ, otherwise a successful campaign has no price")
        qtys = [t.min_qty for t in self.tiers]
        if len(set(qtys)) != len(qtys):
            raise RuleError("duplicate tier thresholds")
        prices = [t.unit_price for t in self.tiers]
        if any(p <= 0 for p in prices):
            raise RuleError("tier prices must be positive")
        if any(b > a for a, b in zip(prices, prices[1:])):
            raise RuleError("price must not rise as quantity rises")
        if self.deadline.tzinfo is None or self.opens_at.tzinfo is None:
            raise RuleError("opens_at and deadline must be timezone-aware")
        if self.deadline <= self.opens_at:
            raise RuleError("deadline must be after opening")
        if self.deadline - self.opens_at >= MAX_CAMPAIGN:
            raise RuleError("deadline must be under 72 hours after opening (PayPal honor period)")
        if len(self.currency) != 3:
            raise RuleError("currency must be an ISO 4217 code")

    @property
    def hold_unit_price(self) -> Decimal:
        """Hold at the highest price a buyer could owe if the MOQ is reached."""
        return self.price_for_total(self.moq)

    def price_for_total(self, total: int) -> Decimal:
        eligible = [t for t in self.tiers if t.min_qty <= max(total, self.moq)]
        return eligible[-1].unit_price if eligible else self.tiers[0].unit_price

    def next_tier(self, total: int) -> Tier | None:
        for t in self.tiers:
            if t.min_qty > total:
                return t
        return None

    def is_open(self, now: datetime) -> bool:
        return self.opens_at <= now < self.deadline


class Outcome(str, Enum):
    TIPPED = "TIPPED"          # MOQ reached: capture everyone at the final tier price
    FAILED = "FAILED"          # MOQ missed: void every hold
    OPEN = "OPEN"


@dataclass(frozen=True)
class Hold:
    participant: str
    authorization_id: str
    amount: Decimal
    authorized_at: datetime
    status: str = "CREATED"     # CREATED | CAPTURED | PARTIALLY_CAPTURED | VOIDED | EXPIRED


@dataclass(frozen=True)
class SettlementAction:
    kind: str                   # "capture" | "void" | "flag"
    participant: str
    authorization_id: str | None
    amount: Decimal | None
    reason: str

    def paypal_request(self, currency: str) -> dict | None:
        if self.kind == "capture":
            return {"method": "POST", "path": f"/v2/payments/authorizations/{self.authorization_id}/capture",
                    "body": {"amount": {"currency_code": currency, "value": str(self.amount)}, "final_capture": True}}
        if self.kind == "void":
            return {"method": "POST", "path": f"/v2/payments/authorizations/{self.authorization_id}/void", "body": None}
        return None


@dataclass
class SettlementPlan:
    outcome: Outcome
    total_qty: int
    unit_price: Decimal | None
    actions: list[SettlementAction]
    shortfall: int = 0

    @property
    def flags(self):
        return [a for a in self.actions if a.kind == "flag"]

    @property
    def capture_total(self) -> Decimal:
        return sum((a.amount for a in self.actions if a.kind == "capture"), Decimal("0.00"))


def hold_amount(campaign: Campaign, qty: int) -> Decimal:
    if qty < 1:
        raise RuleError("quantity must be at least 1")
    if campaign.max_per_person and qty > campaign.max_per_person:
        raise RuleError(f"max {campaign.max_per_person} per person")
    return (campaign.hold_unit_price * qty).quantize(CENT, ROUND_HALF_UP)


def plan_settlement(campaign: Campaign, quantities: dict[str, int], holds: dict[str, list[Hold]],
                    now: datetime, honor_period: timedelta = timedelta(days=3)) -> SettlementPlan:
    """Decide capture-or-void for every hold. Pure function: returns a plan, executes nothing.

    quantities: final committed quantity per participant (from the chat ledger).
    holds: live authorizations per participant (a participant may have a top-up hold).
    Only participants with a covering hold count toward the MOQ; others are flagged.
    """
    if now < campaign.deadline:
        return SettlementPlan(Outcome.OPEN, sum(quantities.values()), None, [])

    actions: list[SettlementAction] = []
    live = {p: [h for h in hs if h.status == "CREATED"] for p, hs in holds.items()}

    # Count what each participant's holds actually cover; an uncovered remainder (raised qty, no top-up) is flagged.
    covered: dict[str, int] = {}
    unit_hold = campaign.hold_unit_price
    for p, q in quantities.items():
        if q <= 0:
            continue
        held = sum((h.amount for h in live.get(p, [])), Decimal("0"))
        held_units = int(held // unit_hold)
        if held_units >= q:
            covered[p] = q
        else:
            if held_units > 0:
                covered[p] = held_units
            actions.append(SettlementAction("flag", p, None, None,
                                            f"committed {q} but holds cover {held_units}; {q - held_units} not counted"))
    total = sum(covered.values())

    if total < campaign.moq:
        for p, hs in live.items():
            for h in hs:
                actions.append(SettlementAction("void", p, h.authorization_id, None,
                                                f"MOQ missed ({total}/{campaign.moq}); release hold"))
        return SettlementPlan(Outcome.FAILED, total, None, actions, shortfall=campaign.moq - total)

    unit = campaign.price_for_total(total)
    for p, hs in live.items():
        owed = (unit * covered.get(p, 0)).quantize(CENT, ROUND_HALF_UP)
        # capture from holds in order; holds past the honor period are flagged (capture not guaranteed)
        for h in sorted(hs, key=lambda h: h.authorized_at):
            if now - h.authorized_at > honor_period:
                actions.append(SettlementAction("flag", p, h.authorization_id, None,
                                                "hold is past the 3-day honor period; reauthorize before capture"))
            if owed > 0:
                take = min(owed, h.amount)
                actions.append(SettlementAction("capture", p, h.authorization_id, take,
                                                f"{covered[p]} x {unit} at tier for total {total}"))
                owed -= take
            else:
                actions.append(SettlementAction("void", p, h.authorization_id, None, "hold not needed"))
    return SettlementPlan(Outcome.TIPPED, total, unit, actions)
