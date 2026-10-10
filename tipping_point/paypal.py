"""PayPal holds adapter: authorize / capture (partial, final) / void. Sandbox only.

FakeHolds mirrors the behaviour observed in the sandbox spike (spikes/SPIKE_RESULT.md):
- capture <= authorized amount with final_capture=true -> auth CAPTURED, remainder released
- capture with final_capture=false -> PARTIALLY_CAPTURED
- capture after final / after void -> AUTHORIZATION_ALREADY_CAPTURED / AUTHORIZATION_VOIDED
- reauthorize inside the 3-day honor period -> REAUTHORIZATION_TOO_SOON
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

SANDBOX = "https://api-m.sandbox.paypal.com"


class PayPalError(RuntimeError):
    def __init__(self, status: int, issue: str | None, body: dict | None = None):
        super().__init__(f"PayPal {status} {issue}")
        self.status, self.issue, self.body = status, issue, body or {}


def load_env_file(path: str) -> dict:
    d = {}
    for line in open(os.path.expanduser(path)):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


class SandboxHolds:
    def __init__(self, client_id: str, client_secret: str, base_url: str = SANDBOX,
                 transport: httpx.BaseTransport | None = None, listener=None):
        if "sandbox" not in base_url:
            raise ValueError("live PayPal URLs are refused; sandbox only")
        self.base = base_url
        self.http = httpx.Client(base_url=base_url, timeout=60, transport=transport)
        self._cid, self._sec = client_id, client_secret
        self._tok, self._exp = None, 0.0
        self.listener = listener   # callable(method, path, status, summary) for the on-screen activity feed

    @classmethod
    def from_env_file(cls, path: str = "~/.secrets/paypal_sandbox.env"):
        e = load_env_file(path)
        return cls(e["PAYPAL_CLIENT_ID"], e["PAYPAL_CLIENT_SECRET"])

    def _token(self) -> str:
        if not self._tok or time.time() > self._exp - 60:
            r = self.http.post("/v1/oauth2/token", auth=(self._cid, self._sec), data={"grant_type": "client_credentials"})
            r.raise_for_status()
            d = r.json()
            self._tok, self._exp = d["access_token"], time.time() + int(d.get("expires_in", 3000))
        return self._tok

    def _call(self, method: str, path: str, body: dict | None = None, request_id: str | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json",
             "Prefer": "return=representation", "PayPal-Request-Id": request_id or str(uuid.uuid4())}
        r = self.http.request(method, path, headers=h, json=body)
        data = r.json() if r.content else {}
        if self.listener:
            amt = None
            if isinstance(body, dict):
                amt = (body.get("amount") or (body.get("purchase_units") or [{}])[0].get("amount") or {}).get("value")
            self.listener(method, path, r.status_code, data.get("status") or
                          ((data.get("details") or [{}])[0].get("issue") if r.status_code >= 400 else ""), amt,
                          r.headers.get("paypal-debug-id"))
        if r.status_code >= 400:
            issue = (data.get("details") or [{}])[0].get("issue") or data.get("name")
            raise PayPalError(r.status_code, issue, data)
        return data

    # --- operations
    def create_hold_order(self, ref: str, amount: Decimal, currency: str, return_url: str, cancel_url: str,
                          description: str, request_id: str | None = None) -> dict:
        body = {"intent": "AUTHORIZE",
                "purchase_units": [{"reference_id": ref, "description": description[:127],
                                    "amount": {"currency_code": currency, "value": str(amount)}}],
                "payment_source": {"paypal": {"experience_context": {
                    "brand_name": "TIPPING POINT", "shipping_preference": "NO_SHIPPING", "user_action": "CONTINUE",
                    "return_url": return_url, "cancel_url": cancel_url}}}}
        d = self._call("POST", "/v2/checkout/orders", body, request_id)
        link = next(l["href"] for l in d["links"] if l["rel"] in ("payer-action", "approve"))
        return {"order_id": d["id"], "approve_url": link, "status": d["status"]}

    def authorize(self, order_id: str, request_id: str | None = None) -> dict:
        d = self._call("POST", f"/v2/checkout/orders/{order_id}/authorize", {}, request_id)
        a = d["purchase_units"][0]["payments"]["authorizations"][0]
        return {"authorization_id": a["id"], "amount": Decimal(a["amount"]["value"]), "status": a["status"],
                "expiration_time": a.get("expiration_time")}

    def capture(self, authorization_id: str, amount: Decimal, currency: str, final: bool = True,
                request_id: str | None = None) -> dict:
        d = self._call("POST", f"/v2/payments/authorizations/{authorization_id}/capture",
                       {"amount": {"currency_code": currency, "value": str(amount)}, "final_capture": final}, request_id)
        return {"capture_id": d["id"], "status": d["status"], "amount": Decimal(d["amount"]["value"])}

    def void(self, authorization_id: str, request_id: str | None = None) -> dict:
        self._call("POST", f"/v2/payments/authorizations/{authorization_id}/void", None, request_id)
        return self.get_authorization(authorization_id)

    def get_order(self, order_id: str) -> dict:
        d = self._call("GET", f"/v2/checkout/orders/{order_id}")
        return {"order_id": d["id"], "status": d["status"]}

    def verify_webhook(self, headers: dict, event: dict, webhook_id: str) -> bool:
        body = {"auth_algo": headers.get("paypal-auth-algo"), "cert_url": headers.get("paypal-cert-url"),
                "transmission_id": headers.get("paypal-transmission-id"),
                "transmission_sig": headers.get("paypal-transmission-sig"),
                "transmission_time": headers.get("paypal-transmission-time"),
                "webhook_id": webhook_id, "webhook_event": event}
        return self._call("POST", "/v1/notifications/verify-webhook-signature", body).get("verification_status") == "SUCCESS"

    def get_authorization(self, authorization_id: str) -> dict:
        d = self._call("GET", f"/v2/payments/authorizations/{authorization_id}")
        return {"authorization_id": d["id"], "status": d["status"], "amount": Decimal(d["amount"]["value"])}


@dataclass
class _FakeAuth:
    id: str
    amount: Decimal
    currency: str
    created: datetime
    status: str = "CREATED"
    captured: Decimal = Decimal("0.00")


@dataclass
class FakeHolds:
    """In-memory stand-in with the sandbox's observed semantics. No network."""
    now: callable = field(default=lambda: datetime.now(timezone.utc))
    orders: dict = field(default_factory=dict)
    auths: dict = field(default_factory=dict)
    seen_requests: dict = field(default_factory=dict)
    listener: object = None
    fail_once: set = field(default_factory=set)     # tests: authorization ids whose next capture/void fails

    def _maybe_fail(self, authorization_id, path):
        if authorization_id in self.fail_once:
            self.fail_once.discard(authorization_id)
            self._log("POST", path, 503, "SERVICE_UNAVAILABLE")
            raise PayPalError(503, "SERVICE_UNAVAILABLE")

    def _log(self, method, path, status, summary, amount=None):
        if self.listener:
            self.listener(method, path, status, summary, amount, None)

    def get_order(self, order_id):
        o = self.orders[order_id]
        return {"order_id": order_id, "status": "COMPLETED" if o.get("authorized") else ("APPROVED" if o["approved"] else "PAYER_ACTION_REQUIRED")}

    def verify_webhook(self, headers, event, webhook_id):
        return headers.get("paypal-transmission-sig") == "fake-valid"

    def create_hold_order(self, ref, amount, currency, return_url, cancel_url, description, request_id=None):
        oid = f"FAKEORDER{len(self.orders)+1:04d}"
        self.orders[oid] = {"ref": ref, "amount": Decimal(amount), "currency": currency, "approved": False,
                            "return_url": return_url}
        self._log("POST", "/v2/checkout/orders", 201, "PAYER_ACTION_REQUIRED", str(amount))
        return {"order_id": oid, "approve_url": f"https://fake.paypal.test/approve/{oid}", "status": "PAYER_ACTION_REQUIRED"}

    def approve(self, order_id):
        self.orders[order_id]["approved"] = True

    def authorize(self, order_id, request_id=None):
        o = self.orders[order_id]
        if not o["approved"]:
            raise PayPalError(422, "ORDER_NOT_APPROVED")
        aid = f"FAKEAUTH{len(self.auths)+1:04d}"
        self.auths[aid] = _FakeAuth(aid, o["amount"], o["currency"], self.now())
        o["authorized"] = True
        self._log("POST", f"/v2/checkout/orders/{order_id}/authorize", 201, "COMPLETED")
        return {"authorization_id": aid, "amount": o["amount"], "status": "CREATED",
                "expiration_time": (self.now() + timedelta(days=29)).isoformat()}

    def capture(self, authorization_id, amount, currency, final=True, request_id=None):
        if request_id and request_id in self.seen_requests:
            return self.seen_requests[request_id]
        self._maybe_fail(authorization_id, f"/v2/payments/authorizations/{authorization_id}/capture")
        a = self.auths[authorization_id]
        if a.status == "VOIDED":
            raise PayPalError(422, "AUTHORIZATION_VOIDED")
        if a.status == "CAPTURED":
            raise PayPalError(422, "AUTHORIZATION_ALREADY_CAPTURED")
        amount = Decimal(amount)
        if a.captured + amount > a.amount:
            raise PayPalError(422, "MAX_CAPTURE_AMOUNT_EXCEEDED")
        a.captured += amount
        a.status = "CAPTURED" if final else "PARTIALLY_CAPTURED"
        self._log("POST", f"/v2/payments/authorizations/{authorization_id}/capture", 201, "COMPLETED", str(amount))
        res = {"capture_id": f"FAKECAP{authorization_id[-4:]}{int(a.captured*100)}", "status": "COMPLETED", "amount": amount}
        if request_id:
            self.seen_requests[request_id] = res
        return res

    def void(self, authorization_id, request_id=None):
        self._maybe_fail(authorization_id, f"/v2/payments/authorizations/{authorization_id}/void")
        a = self.auths[authorization_id]
        if a.status in ("CAPTURED",):
            raise PayPalError(422, "AUTHORIZATION_ALREADY_CAPTURED")
        a.status = "VOIDED"
        self._log("POST", f"/v2/payments/authorizations/{authorization_id}/void", 204, "VOIDED")
        return self.get_authorization(authorization_id)

    def reauthorize(self, authorization_id):
        a = self.auths[authorization_id]
        if self.now() - a.created <= timedelta(days=3):
            raise PayPalError(422, "REAUTHORIZATION_TOO_SOON")
        a.created = self.now()
        return {"authorization_id": a.id, "status": "CREATED"}

    def get_authorization(self, authorization_id):
        a = self.auths[authorization_id]
        return {"authorization_id": a.id, "status": a.status, "amount": a.amount}
