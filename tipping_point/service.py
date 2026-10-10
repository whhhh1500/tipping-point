"""Application service: one campaign's lifecycle, independent of the web layer.

chat -> order list -> hold links -> buyer approvals (holds) -> close -> approved settlement -> captures/releases
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .campaign import CENT, Campaign, RuleError, Hold, Outcome, Tier, hold_amount, plan_settlement
from .chat import parse_export
from .events import Kind
from .ledger import build_order_list
from .readers import ReaderContext, StubReader, is_organiser
from .settle import execute, plan_hash

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def utcnow():
    return datetime.now(timezone.utc)


@dataclass
class HoldRec:
    id: str
    participant: str
    qty: int
    amount: Decimal
    order_id: str
    approve_url: str
    kind: str = "initial"            # initial | top-up
    status: str = "LINK_SENT"        # LINK_SENT | HELD | CAPTURED | RELEASED | NOT_HELD | CANCELLED
    authorization_id: str | None = None
    captured: Decimal | None = None
    created_at: datetime = field(default_factory=utcnow)
    held_at: datetime | None = None
    payer: str | None = None         # wallet | guest (demo runner) or None


@dataclass
class CampaignState:
    id: str
    campaign: Campaign
    ctx: ReaderContext
    chat_text: str
    sample: str | None = None
    messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    order_list: object = None
    holds: dict = field(default_factory=dict)
    plan: object = None
    plan_hash: str | None = None
    results: list | None = None
    activity: list = field(default_factory=list)
    stage: str = "draft"             # draft | read | collecting | closed | settled
    demo_running: bool = False
    demo_log: list | None = None
    demo_progress: dict | None = None
    settle_errors: list = field(default_factory=list)
    reader_used: str | None = None      # which reader actually produced this campaign's events


def load_sample(name: str) -> tuple[str, dict]:
    exp = json.loads((FIXTURES / "expected.json").read_text())[name]
    return (FIXTURES / name).read_text(), exp


SAMPLES = {
    "durian": "durian_tampines_whatsapp_android.txt",
    "socks": "house_socks_whatsapp_ios.txt",
    "keycaps": "keycaps_telegram_export.json",
}


def _append_line(chat_text: str, sender: str, body: str, ts: datetime) -> str:
    if chat_text.lstrip().startswith("{"):
        d = json.loads(chat_text)
        nid = max((m.get("id", 0) for m in d.get("messages", [])), default=0) + 1
        d.setdefault("messages", []).append({"id": nid, "type": "message", "date": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                                             "from": sender, "text": body})
        return json.dumps(d, ensure_ascii=False, indent=1)
    ios = any(l.startswith("[") for l in chat_text.splitlines()[:5])
    if ios:
        line = f"[{ts.strftime('%d/%m/%y')}, {ts.strftime('%I:%M:%S %p').lstrip('0')}] {sender}: {body}"
    else:
        line = f"{ts.strftime('%d/%m/%y')}, {ts.strftime('%H:%M')} - {sender}: {body}"
    return chat_text.rstrip("\n") + "\n" + line + "\n"


def _chip(e) -> str:
    v = f" {e.variant}" if e.variant else ""
    return {Kind.SET: f"{e.qty}{v}", Kind.ADD: f"+{e.qty}{v}", Kind.REMOVE: f"−{e.qty}{v}",
            Kind.CANCEL: f"cancel{v}", Kind.SET_VARIANT: f"→{v}", Kind.COPY: f"= {e.copy_from}",
            Kind.MAYBE: f"maybe {e.qty or ''}{v}".strip(), Kind.QUESTION: "question"}[e.kind]


class Service:
    def __init__(self, api, base_url: str = "http://127.0.0.1:8000", reader=None, now=utcnow, mode: str = "fake"):
        self.api, self.base_url, self.reader, self.now, self.mode = api, base_url.rstrip("/"), reader or StubReader(), now, mode
        self.campaigns: dict[str, CampaignState] = {}
        self.lock = threading.RLock()
        self._current: CampaignState | None = None
        if hasattr(api, "listener"):
            api.listener = self._on_paypal_call

    # ---------------------------------------------------------------- activity feed
    def _on_paypal_call(self, method, path, status, summary, amount, debug_id):
        if self._current is not None:
            self._current.activity.append({"t": self.now().isoformat(timespec="seconds"), "method": method,
                                           "path": path, "status": status, "summary": summary, "amount": amount,
                                           "debug_id": debug_id})

    def _use(self, st):
        self._current = st
        return st

    # ---------------------------------------------------------------- campaign
    def create(self, sample: str | None = None, chat_text: str | None = None, config: dict | None = None) -> CampaignState:
        with self.lock:
            if sample:
                sample_text, exp = load_sample(SAMPLES.get(sample, sample))
                chat_text = chat_text or sample_text
                config = {**exp["campaign"], **exp["ctx"], **(config or {})}
            config = config or {}
            if not config.get("moq") or not config.get("tiers"):
                raise RuleError("set a minimum quantity and at least one price tier")
            opens = self.now()
            c = Campaign(id=uuid.uuid4().hex[:8], item=config.get("item", "Group buy"), currency=config.get("currency", "SGD"),
                         moq=int(config["moq"]), tiers=[Tier(int(a), Decimal(str(b))) for a, b in config["tiers"]],
                         opens_at=opens, deadline=opens + timedelta(hours=float(config.get("hours", 48))),
                         variants=list(config.get("variants", [])), max_per_person=config.get("max_per_person"))
            ctx = ReaderContext(config.get("organiser", ""), c.variants, dict(config.get("aliases", {})))
            st = CampaignState(c.id, c, ctx, chat_text or "", sample=sample)
            self.campaigns[c.id] = st
            return st

    def read(self, cid: str) -> CampaignState:
        with self.lock:
            st = self.campaigns[cid]
            text, ctx = st.chat_text, st.ctx
        messages = parse_export(text)
        events = self.reader.extract(messages, ctx)          # outside the lock: a model call can take seconds
        with self.lock:
            st = self.campaigns[cid]
            st.messages, st.events = messages, events
            st.reader_used = getattr(self.reader, "last_used", None) or self.reader.name
            st.order_list = build_order_list(st.events, st.ctx.variants, st.campaign.max_per_person)
            if st.stage == "draft":
                st.stage = "read"
            return st

    def append_chat(self, cid: str, text: str) -> CampaignState:
        """Append 'Name: message' lines in the export's own format (so the demo can show a late change)."""
        with self.lock:
            st = self.campaigns[cid]
            if st.stage in ("closed", "settled"):
                raise ValueError("campaign is closed")
            msgs = parse_export(st.chat_text)
            last = max((m.ts for m in msgs if m.ts), default=datetime(2026, 10, 10, 12, 0))
            for raw in [l for l in text.splitlines() if l.strip()]:
                if ":" not in raw:
                    raise ValueError("use the form  Name: message")
                sender, body = (x.strip() for x in raw.split(":", 1))
                last = last + timedelta(minutes=1)
                st.chat_text = _append_line(st.chat_text, sender, body, last)
            return self.read(cid)

    # ---------------------------------------------------------------- holds
    def coverage(self, st: CampaignState) -> dict[str, dict]:
        out = {}
        committed = st.order_list.by_participant() if st.order_list else {}
        names = set(committed) | {h.participant for h in st.holds.values()}
        for p in names:
            hs = [h for h in st.holds.values() if h.participant == p]
            held = sum(h.qty for h in hs if h.status == "HELD")
            pending = sum(h.qty for h in hs if h.status == "LINK_SENT")
            q = committed.get(p, 0)
            out[p] = {"committed": q, "held": held, "pending": pending, "needs": max(q - held - pending, 0)}
        return out

    def send_holds(self, cid: str) -> list[HoldRec]:
        with self.lock:
            st = self._use(self.campaigns[cid])
            if st.stage in ("closed", "settled"):
                raise ValueError("campaign is closed")
            created = []
            for p, cov in sorted(self.coverage(st).items()):
                if cov["needs"] <= 0:
                    continue
                hid = uuid.uuid4().hex[:10]
                amt = hold_amount(st.campaign, cov["needs"])
                kind = "top-up" if any(h.participant == p for h in st.holds.values()) else "initial"
                o = self.api.create_hold_order(
                    ref=f"TP-{cid}-{hid}", amount=amt, currency=st.campaign.currency,
                    return_url=f"{self.base_url}/r/{cid}/{hid}", cancel_url=f"{self.base_url}/x/{cid}/{hid}",
                    description=f"TEST ONLY - sandbox group-buy hold: {cov['needs']} x {st.campaign.item}",
                    request_id=f"tp-{cid}-{hid}-create")
                h = HoldRec(hid, p, cov["needs"], amt, o["order_id"], o["approve_url"], kind)
                st.holds[hid] = h
                created.append(h)
            if st.holds:
                st.stage = "collecting"
            return created

    def on_return(self, cid: str, hid: str) -> HoldRec:
        """Buyer came back from PayPal approval: place the authorization hold (idempotent)."""
        with self.lock:
            st = self._use(self.campaigns[cid])
            h = st.holds[hid]
            if h.status != "LINK_SENT":
                return h
            a = self.api.authorize(h.order_id, request_id=f"tp-{cid}-{hid}-authorize")
            h.authorization_id, h.status, h.held_at = a["authorization_id"], "HELD", self.now()
            return h

    def on_cancel(self, cid: str, hid: str) -> HoldRec:
        with self.lock:
            h = self.campaigns[cid].holds[hid]
            if h.status == "LINK_SENT":
                h.status = "CANCELLED"
            return h

    def sync(self, cid: str) -> CampaignState:
        """Status updates without webhooks: approved-but-not-returned orders get authorized; held auths re-read."""
        with self.lock:
            st = self._use(self.campaigns[cid])
            for h in list(st.holds.values()):
                if h.status == "LINK_SENT":
                    if self.api.get_order(h.order_id)["status"] == "APPROVED":
                        self.on_return(cid, h.id)
                elif h.status == "HELD":
                    s = self.api.get_authorization(h.authorization_id)["status"]
                    if s == "VOIDED":
                        h.status = "RELEASED"
                    elif s == "EXPIRED":
                        h.status = "NOT_HELD"
            return st

    def on_webhook(self, event: dict) -> str:
        """Hosted mode: PayPal webhook (signature verified by the web layer)."""
        with self.lock:
            et, res = event.get("event_type", ""), event.get("resource", {})
            for st in self.campaigns.values():
                for h in st.holds.values():
                    if et == "CHECKOUT.ORDER.APPROVED" and res.get("id") == h.order_id and h.status == "LINK_SENT":
                        self.on_return(st.id, h.id)
                        return "authorized"
                    if et == "PAYMENT.AUTHORIZATION.VOIDED" and res.get("id") == h.authorization_id and h.status == "HELD":
                        h.status = "RELEASED"
                        return "released"
            return "ignored"

    # ---------------------------------------------------------------- close & settle
    def close(self, cid: str) -> CampaignState:
        with self.lock:
            st = self._use(self.campaigns[cid])
            if st.stage == "settled":
                return st
            now = self.now()
            if now < st.campaign.deadline:   # organiser closes early: the deadline becomes now
                st.campaign.deadline = max(now, st.campaign.opens_at + timedelta(seconds=1))
            holds = {}
            for h in st.holds.values():
                if h.status == "HELD":
                    holds.setdefault(h.participant, []).append(
                        Hold(h.participant, h.authorization_id, h.amount, h.held_at or now))
            quantities = st.order_list.by_participant()
            st.plan = plan_settlement(st.campaign, quantities, holds, now=max(now, st.campaign.deadline))
            st.plan_hash = plan_hash(st.plan, st.campaign.currency)
            st.stage = "closed"
            return st

    def settle(self, cid: str, approved_hash: str) -> CampaignState:
        """Run the approved plan. If any PayPal call fails the campaign stays 'closed' so the organiser can retry;
        retries reuse the same PayPal-Request-Ids, so calls that already succeeded are not repeated."""
        with self.lock:
            st = self._use(self.campaigns[cid])
            if st.stage == "settled":
                return st
            if st.stage != "closed":
                raise ValueError("close the campaign first")
            st.results = execute(st.plan, st.campaign.currency, approved_hash, self.api, cid)
            by_auth = {h.authorization_id: h for h in st.holds.values() if h.authorization_id}
            st.settle_errors = []
            for a, r in zip(st.plan.actions, st.results):
                h = by_auth.get(a.authorization_id)
                if not h:
                    continue
                if not r["ok"]:
                    h.status = "ERROR"
                    st.settle_errors.append({"participant": a.participant, "action": a.kind, "issue": r.get("error")})
                elif a.kind == "capture":
                    h.status, h.captured = "CAPTURED", a.amount
                elif a.kind == "void":
                    h.status, h.captured = "RELEASED", Decimal("0.00")
            if st.settle_errors:
                return st
            for h in st.holds.values():
                if h.status == "LINK_SENT":
                    h.status = "NOT_HELD"      # buyer never approved: nothing to release
            st.stage = "settled"
            return st

    # ---------------------------------------------------------------- view model
    def view(self, cid: str) -> dict:
        with self.lock:
            st = self.campaigns[cid]
            c = st.campaign
            ol = st.order_list
            cov = self.coverage(st) if ol else {}
            committed = ol.total if ol else 0
            held_qty = sum(v["held"] for v in cov.values())
            if st.stage in ("closed", "settled") and st.plan:
                held_qty = st.plan.total_qty          # what counted at close, even after holds are released
            counted = held_qty if st.holds else committed
            unit_now = c.price_for_total(counted) if counted >= c.moq else c.hold_unit_price
            nxt = c.next_tier(counted)
            issue_src = {i.source_id for i in (ol.issues if ol else [])}
            ev_by_msg: dict[int, list] = {}
            for e in st.events:
                ev_by_msg.setdefault(e.source_id, []).append(e)
            msgs = []
            for m in st.messages:
                evs = ev_by_msg.get(m.id, [])
                org = is_organiser(m.sender, st.ctx)
                cls = "organiser" if org and not evs else (
                    "flag" if (m.id in issue_src or any(e.kind in (Kind.MAYBE, Kind.QUESTION) for e in evs)) else
                    ("order" if evs else "chatter"))
                msgs.append({"id": m.id, "sender": m.sender, "text": m.text,
                             "time": m.ts.strftime("%H:%M") if m.ts else "", "cls": cls,
                             "chips": [{"text": _chip(e), "kind": e.kind.value,
                                        "who": e.participant if e.participant != m.sender else None} for e in evs]})
            rows = []
            for p in sorted(cov):
                lines = [l for l in ol.lines if l.participant == p] if ol else []
                hs = [h for h in st.holds.values() if h.participant == p]
                items = ", ".join(f"{l.qty} {l.variant}" if l.variant else str(l.qty) for l in sorted(lines, key=lambda l: l.variant or ""))
                held_amt = sum((h.amount for h in hs if h.status in ("HELD", "CAPTURED", "RELEASED")), Decimal("0"))
                captured = sum((h.captured or Decimal("0") for h in hs if h.status == "CAPTURED"), Decimal("0"))
                statuses = [h.status for h in hs]
                status = ("PAYPAL ERROR" if "ERROR" in statuses else "CAPTURED" if "CAPTURED" in statuses else "RELEASED" if "RELEASED" in statuses and "HELD" not in statuses
                          else ("TOP-UP NEEDED" if cov[p]["needs"] and cov[p]["held"] and st.stage == "collecting" else
                                "HELD" if cov[p]["held"] >= cov[p]["committed"] and cov[p]["held"] else
                                "AWAITING BUYER" if cov[p]["pending"] else
                                "NOT HELD" if st.stage == "settled" else ("CANCELLED" if cov[p]["committed"] == 0 else "NO LINK YET")))
                rows.append({"participant": p, "items": items or "—", "qty": cov[p]["committed"],
                             "held_qty": cov[p]["held"], "hold_amount": str(held_amt.quantize(CENT)),
                             "captured": str(captured.quantize(CENT)) if st.stage == "settled" else "",
                             "released": str((held_amt - captured).quantize(CENT)) if st.stage == "settled" else "",
                             "status": status,
                             "auth_ids": [h.authorization_id for h in hs if h.authorization_id],
                             "links": [{"id": h.id, "url": h.approve_url, "kind": h.kind, "status": h.status, "qty": h.qty,
                                        "amount": str(h.amount)} for h in hs],
                             "added_by": next((l.added_by for l in lines if l.added_by), None)})
            plan = None
            if st.plan:
                plan = {"outcome": st.plan.outcome.value, "total_qty": st.plan.total_qty,
                        "unit_price": str(st.plan.unit_price) if st.plan.unit_price else None,
                        "shortfall": st.plan.shortfall, "hash": st.plan_hash,
                        "capture_total": str(st.plan.capture_total),
                        "actions": [{"kind": a.kind, "participant": a.participant, "auth": a.authorization_id,
                                     "amount": str(a.amount) if a.amount is not None else None, "reason": a.reason,
                                     "request": a.paypal_request(c.currency)} for a in st.plan.actions]}
            held_total = sum((h.amount for h in st.holds.values() if h.status in ("HELD", "CAPTURED", "RELEASED")), Decimal("0"))
            cap_total = sum((h.captured or Decimal("0") for h in st.holds.values() if h.status == "CAPTURED"), Decimal("0"))
            return {
                "id": st.id, "stage": st.stage, "mode": self.mode, "reader": self.reader.name, "reader_used": st.reader_used, "reader_note": getattr(self.reader, "last_note", None), "demo_running": st.demo_running, "demo_log": st.demo_log, "demo_progress": st.demo_progress,
                "settle_errors": st.settle_errors,
                "campaign": {"item": c.item, "currency": c.currency, "moq": c.moq, "deadline": c.deadline.isoformat(),
                             "opens_at": c.opens_at.isoformat(), "organiser": st.ctx.organiser, "variants": c.variants,
                             "tiers": [{"min_qty": t.min_qty, "unit_price": str(t.unit_price)} for t in c.tiers],
                             "hold_unit_price": str(c.hold_unit_price)},
                "progress": {"committed": committed, "held": held_qty, "counted": counted, "moq": c.moq,
                             "tipped": counted >= c.moq, "unit_now": str(unit_now),
                             "next_tier": {"min_qty": nxt.min_qty, "unit_price": str(nxt.unit_price)} if nxt else None},
                "messages": msgs, "rows": rows,
                "issues": [{"kind": i.kind, "participant": i.participant, "source_id": i.source_id, "detail": i.detail,
                            "draft_reply": i.draft_reply} for i in (ol.issues if ol else [])],
                "plan": plan, "results": st.results,
                "totals": {"held": str(held_total.quantize(CENT)), "captured": str(cap_total.quantize(CENT)),
                           "released": str((held_total - cap_total).quantize(CENT)) if st.stage == "settled" else None},
                "activity": st.activity[-40:],
            }
