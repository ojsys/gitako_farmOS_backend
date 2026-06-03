"""Payment provider seam (shared by M17 escrow + M18 disbursement).

Mirrors the SMS / push / LLM seams. Two providers behind one interface:
- **StubPaymentProvider** (default, no keys): deterministic in-memory "charges"
  and "transfers" that always succeed and return synthetic references. Lets the
  escrow + loan state machines run and test end-to-end without moving real money.
- **PaystackProvider**: lazy-imports `requests`, calls the live Paystack API.
  Activated with PAYMENT_PROVIDER=paystack + PAYSTACK_SECRET_KEY.

A "charge" pulls money in (buyer funds escrow); a "transfer" pushes money out
(release to seller, disburse a loan). Both return a PaymentResult with a
provider reference and status.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from django.conf import settings

log = logging.getLogger("gitako.payments")


@dataclass
class PaymentResult:
    ok: bool
    reference: str
    status: str  # "succeeded" | "pending" | "failed"
    raw: dict | None = None


class PaymentProvider(Protocol):
    def charge(self, *, amount_kobo: int, reference: str, description: str = "") -> PaymentResult: ...
    def transfer(self, *, amount_kobo: int, recipient: str, reference: str, description: str = "") -> PaymentResult: ...


class StubPaymentProvider:
    """Deterministic, always-succeeds. Reference encodes the intent so tests and
    logs are readable. No real money moves."""

    def charge(self, *, amount_kobo, reference, description=""):
        log.info("STUB charge %d kobo ref=%s (%s)", amount_kobo, reference, description)
        return PaymentResult(ok=True, reference=f"stub_chg_{reference}", status="succeeded",
                             raw={"stub": True, "amount_kobo": amount_kobo})

    def transfer(self, *, amount_kobo, recipient, reference, description=""):
        log.info("STUB transfer %d kobo → %s ref=%s (%s)", amount_kobo, recipient, reference, description)
        return PaymentResult(ok=True, reference=f"stub_trf_{reference}", status="succeeded",
                             raw={"stub": True, "amount_kobo": amount_kobo, "recipient": recipient})


class PaystackProvider:
    BASE_URL = "https://api.paystack.co"

    def _headers(self):
        key = settings.GITAKO.get("PAYSTACK_SECRET_KEY", "")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def charge(self, *, amount_kobo, reference, description=""):
        # Real escrow funding is initialized via Paystack and confirmed by webhook;
        # this initializes the transaction. Falls back to stub if unconfigured.
        if not settings.GITAKO.get("PAYSTACK_SECRET_KEY"):
            log.warning("Paystack not configured; using stub charge")
            return StubPaymentProvider().charge(amount_kobo=amount_kobo, reference=reference, description=description)
        import requests
        resp = requests.post(
            f"{self.BASE_URL}/transaction/initialize",
            json={"amount": amount_kobo, "reference": reference, "metadata": {"description": description}},
            headers=self._headers(), timeout=15,
        )
        ok = resp.status_code < 300 and resp.json().get("status") is True
        return PaymentResult(ok=ok, reference=reference, status="pending" if ok else "failed", raw=resp.json())

    def transfer(self, *, amount_kobo, recipient, reference, description=""):
        if not settings.GITAKO.get("PAYSTACK_SECRET_KEY"):
            log.warning("Paystack not configured; using stub transfer")
            return StubPaymentProvider().transfer(amount_kobo=amount_kobo, recipient=recipient,
                                                  reference=reference, description=description)
        import requests
        resp = requests.post(
            f"{self.BASE_URL}/transfer",
            json={"source": "balance", "amount": amount_kobo, "recipient": recipient,
                  "reference": reference, "reason": description},
            headers=self._headers(), timeout=15,
        )
        ok = resp.status_code < 300 and resp.json().get("status") is True
        return PaymentResult(ok=ok, reference=reference, status="pending" if ok else "failed", raw=resp.json())


def get_payment_provider() -> PaymentProvider:
    name = settings.GITAKO.get("PAYMENT_PROVIDER", "stub")
    if name == "paystack":
        return PaystackProvider()
    return StubPaymentProvider()


def new_reference(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"
