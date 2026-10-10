"""Execute an approved settlement plan. The only code path that moves money.

Approval is bound to a hash of the exact plan the organiser saw; any change voids the approval.
Each action uses a deterministic PayPal-Request-Id so retries are idempotent.
"""
from __future__ import annotations

import hashlib
import json

from .campaign import SettlementPlan
from .paypal import PayPalError


def plan_hash(plan: SettlementPlan, currency: str) -> str:
    payload = [{"kind": a.kind, "participant": a.participant, "auth": a.authorization_id,
                "amount": str(a.amount) if a.amount is not None else None} for a in plan.actions]
    raw = json.dumps({"outcome": plan.outcome.value, "currency": currency, "actions": payload}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class ApprovalError(PermissionError):
    pass


def execute(plan: SettlementPlan, currency: str, approved_hash: str, holds_api, campaign_id: str) -> list[dict]:
    if approved_hash != plan_hash(plan, currency):
        raise ApprovalError("plan changed after approval (or was never approved)")
    results = []
    for i, a in enumerate(plan.actions):
        rid = f"tp-{campaign_id}-{plan_hash(plan, currency)[:12]}-{i}"
        try:
            if a.kind == "capture":
                r = holds_api.capture(a.authorization_id, a.amount, currency, final=True, request_id=rid)
            elif a.kind == "void":
                r = holds_api.void(a.authorization_id, request_id=rid)
            else:
                r = {"skipped": "flag"}
            results.append({"action": a.kind, "participant": a.participant, "ok": True, "result": r})
        except PayPalError as e:
            results.append({"action": a.kind, "participant": a.participant, "ok": False, "error": e.issue})
    return results
