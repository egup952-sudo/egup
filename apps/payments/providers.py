"""
PaymentProvider abstraction (migration brief section 10).

PayHeroProvider below is a faithful Python port of the audited
worker/src/lib/payhero.js from the Supabase/Worker project — same
endpoints, same field names, same verification notes. It is a port, not a
rewrite: every field name and the reference-vs-checkout_request_id
distinction were independently verified there against PayHero's own docs
and their official PHP client on 2026-08-10, and that verification is not
being redone or second-guessed here.

=========================================================================
VERIFIED (carried over from the audited source):
  - Base URL: https://backend.payhero.co.ke/api/v2/
  - Auth: `Authorization: Basic ` + base64(api_username + ':' + api_password)
  - STK push: POST payments
      body: {amount, phone_number, channel_id, external_reference,
             callback_url, provider: 'm-pesa'}
      response: {"success": true, "status": "QUEUED", "reference": "...",
                 "CheckoutRequestID": "ws_CO_..."}
      NOTE: `reference` and `CheckoutRequestID` are two DIFFERENT values.
  - Status check: GET transaction-status?reference=<reference>
      Uses `reference`, NOT `CheckoutRequestID`.

UNVERIFIED (also carried over as an explicit, not-hidden gap):
  - The exact JSON shape PayHero POSTs to our callback_url on settlement.
  - Any signature/HMAC/authenticity mechanism for that callback — none was
    found in PayHero's official docs, PHP client, or sample repos. Treated
    as CONFIRMED ABSENT, not assumed present.

SECURITY CONSEQUENCE: the callback body is NEVER trusted for status. It
only identifies which local Payment row to re-verify. The only call
allowed to conclude PAID is verify_transaction_status(), an authenticated
server-to-server GET using our own credentials. See services.py.

Before this goes live, re-confirm these details still hold against
PayHero's current docs (docs.payhero.co.ke) — APIs change, and this
verification is dated 2026-08-10.
=========================================================================
"""
import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests
from django.conf import settings

PAYHERO_BASE_URL = "https://backend.payhero.co.ke/api/v2"


class PaymentProviderError(Exception):
    def __init__(self, message, status=None, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class StkPushResult:
    provider_reference: Optional[str]
    checkout_request_id: Optional[str]
    raw: dict


@dataclass
class StatusResult:
    status: str  # PENDING | PAID | FAILED | CANCELLED | EXPIRED
    mpesa_receipt: Optional[str]
    amount: Optional[int]
    external_reference: Optional[str]
    checkout_request_id: Optional[str]
    raw: dict


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def initiate_stk_push(self, *, amount, phone_number, reference, callback_url, customer_name=None) -> StkPushResult:
        ...

    @abstractmethod
    def verify_transaction_status(self, provider_reference: str) -> StatusResult:
        ...

    @abstractmethod
    def extract_callback_identifiers(self, body: dict) -> dict:
        """Low-trust parse of an inbound callback body. Used ONLY to pick
        which local Payment row to re-verify — never to decide status."""
        ...


class PayHeroProvider(PaymentProvider):
    name = "PAYHERO"

    def _credentials(self):
        """DB-stored (encrypted) credentials take priority when set via
        the admin dashboard; environment variables are the fallback —
        see apps.payments.models.PaymentCredentials and crypto.py."""
        from .models import PaymentCredentials

        creds = PaymentCredentials.get_solo()
        return {
            "username": creds.payhero_api_username or settings.PAYHERO_API_USERNAME,
            "password": creds.payhero_api_password or settings.PAYHERO_API_PASSWORD,
            "channel_id": creds.payhero_channel_id or settings.PAYHERO_CHANNEL_ID,
        }

    def _auth_header(self):
        creds = self._credentials()
        token = base64.b64encode(f"{creds['username']}:{creds['password']}".encode()).decode()
        return f"Basic {token}"

    def initiate_stk_push(self, *, amount, phone_number, reference, callback_url, customer_name=None) -> StkPushResult:
        creds = self._credentials()
        body = {
            "amount": amount,
            "phone_number": phone_number,
            "channel_id": creds["channel_id"],
            "provider": "m-pesa",
            "external_reference": reference,
        }
        if callback_url:
            body["callback_url"] = callback_url
        if customer_name:
            body["customer_name"] = customer_name

        resp = requests.post(
            f"{PAYHERO_BASE_URL}/payments",
            json=body,
            headers={"Authorization": self._auth_header(), "Content-Type": "application/json"},
            timeout=30,
        )
        try:
            response_body = resp.json()
        except ValueError:
            response_body = {}
        if not resp.ok:
            raise PaymentProviderError(f"PayHero STK push failed: {resp.status_code}", resp.status_code, response_body)

        return StkPushResult(
            provider_reference=response_body.get("reference"),
            checkout_request_id=response_body.get("CheckoutRequestID"),
            raw=response_body,
        )

    def verify_transaction_status(self, provider_reference: str) -> StatusResult:
        resp = requests.get(
            f"{PAYHERO_BASE_URL}/transaction-status",
            params={"reference": provider_reference},
            headers={"Authorization": self._auth_header()},
            timeout=30,
        )
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not resp.ok:
            raise PaymentProviderError(f"PayHero status check failed: {resp.status_code}", resp.status_code, body)
        return self._normalize_status(body)

    @staticmethod
    def _normalize_status(body: dict) -> StatusResult:
        container = body.get("response", body) if isinstance(body, dict) else {}
        result_code = container.get("ResultCode", container.get("resultCode"))
        raw_status = str(container.get("Status", container.get("status", ""))).upper()

        status = "PENDING"
        if result_code == 0 or raw_status in ("SUCCESS", "COMPLETED", "PAID"):
            status = "PAID"
        elif raw_status in ("CANCELLED", "CANCELED") or result_code == 1032:
            status = "CANCELLED"
        elif raw_status in ("EXPIRED", "TIMEOUT") or result_code == 1037:
            status = "EXPIRED"
        elif result_code is not None:
            status = "FAILED"
        elif raw_status and raw_status not in ("PENDING", "QUEUED"):
            status = "FAILED"

        return StatusResult(
            status=status,
            mpesa_receipt=container.get("MpesaReceiptNumber", container.get("mpesa_receipt_number")),
            amount=container.get("Amount", container.get("amount")),
            external_reference=container.get("ExternalReference", container.get("external_reference")),
            checkout_request_id=container.get("CheckoutRequestID"),
            raw=body,
        )

    def extract_callback_identifiers(self, body: dict) -> dict:
        container = (body or {}).get("response", body) or {}
        return {
            "external_reference": container.get("ExternalReference", container.get("external_reference", body.get("external_reference"))),
            "provider_reference": container.get("reference", body.get("reference")),
            "checkout_request_id": container.get("CheckoutRequestID", body.get("CheckoutRequestID")),
        }


class DarajaProvider(PaymentProvider):
    """Secondary/fallback provider. NOT held to the same verification
    standard as PayHeroProvider yet — Project A's mpesa.py is the starting
    point but has no equivalent audit or test coverage. Treat as
    documented-but-unverified until it gets the same scrutiny PayHero got.
    Kept as a stub interface per the brief's "PaymentService decides which
    provider" design, wired but not defaulted to.
    """

    name = "DARAJA"

    def initiate_stk_push(self, *, amount, phone_number, reference, callback_url, customer_name=None) -> StkPushResult:
        raise NotImplementedError(
            "DarajaProvider is not yet ported/audited. See apps/payments_legacy_ref "
            "for Project A's original mpesa.py as a starting point."
        )

    def verify_transaction_status(self, provider_reference: str) -> StatusResult:
        raise NotImplementedError("DarajaProvider is not yet ported/audited.")

    def extract_callback_identifiers(self, body: dict) -> dict:
        raise NotImplementedError("DarajaProvider is not yet ported/audited.")


def get_provider(name: str = "PAYHERO") -> PaymentProvider:
    return {"PAYHERO": PayHeroProvider, "DARAJA": DarajaProvider}[name]()


def is_automatic_payment_available() -> bool:
    """Intelligent mode detection (spec section 3): automatic (STK push)
    is only offered if BOTH an admin has explicitly enabled it AND real
    PayHero credentials are actually configured (DB or env — see
    PayHeroProvider._credentials). This is checked fresh on every
    registration/renewal page load, not cached — if PayHero credentials
    are removed or an admin flips the toggle off, the automatic option
    disappears immediately and manual payment (if enabled) keeps working
    without any code change or deploy. Never raises — a misconfiguration
    here means "automatic unavailable," not a 500 error for an applicant.
    """
    try:
        from apps.members.models import SystemSettings

        settings_obj = SystemSettings.get_solo()
        if not settings_obj.automatic_payment_enabled:
            return False
        creds = PayHeroProvider()._credentials()
        return bool(creds["username"] and creds["password"] and creds["channel_id"])
    except Exception:
        return False


def is_manual_payment_available() -> bool:
    try:
        from apps.members.models import SystemSettings

        return SystemSettings.get_solo().manual_payment_enabled
    except Exception:
        return True  # fail open for manual — it's the fallback path, must never silently vanish
