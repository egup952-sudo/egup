"""SMS delivery for renewal OTPs (apps.members.models.RenewalOTP).

IMPORTANT — this is a stub, not a working integration. There is no SMS
provider account/API key anywhere in this codebase (checked: no
Africa's Talking, Twilio, or similar dependency exists at all). Wiring
one in requires a decision only the site owner can make (which provider,
which account) plus real credentials — something I cannot invent.

Until a real provider is configured, this logs the OTP server-side
(logger.info, NOT print — reaches your actual server logs) instead of
silently pretending to send it. That keeps renewal functionally usable
during setup/testing (an admin with server log access can read the code
and hand it to whoever's renewing) while making it completely obvious,
every single time, that nothing is actually being delivered to a phone.

To go live: implement `_send_via_provider` below with your chosen
gateway's API call, and set SMS_PROVIDER (env var) to anything truthy so
`send_otp_sms` stops using the log-only fallback. NEVER log the OTP
itself once a real provider is wired in — that line is deliberately
gated on `not settings.SMS_PROVIDER_CONFIGURED` for exactly that reason.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def _send_via_provider(phone_number: str, message: str) -> bool:
    """Replace this with a real SMS gateway call (Africa's Talking,
    Twilio, etc.) once credentials are available. Must return True only
    on confirmed acceptance by the provider, never assume success."""
    raise NotImplementedError(
        "No SMS provider is configured. Set up a real gateway in "
        "_send_via_provider() before enabling SMS_PROVIDER."
    )


def send_otp_sms(phone_number: str, code: str) -> bool:
    """Returns True if the code was (or, in the log-only fallback,
    would need to be) delivered. Callers must NOT treat a False return
    as "the OTP doesn't exist" — it still does, and still counts against
    rate limits; it just wasn't deliverable right now."""
    message = f"Your EGUP renewal code is {code}. It expires in 5 minutes. Do not share this code with anyone."

    if not getattr(settings, "SMS_PROVIDER_CONFIGURED", False):
        # Deliberately the ONLY place in this codebase an OTP value is
        # ever allowed to reach a log — see module docstring. This branch
        # must stop being reachable the moment a real provider is set up.
        logger.warning(
            "SMS provider not configured — OTP for %s would be: %s (this MUST NOT happen in production; "
            "set SMS_PROVIDER_CONFIGURED once a real gateway is wired into _send_via_provider)",
            phone_number, code,
        )
        return True

    try:
        return _send_via_provider(phone_number, message)
    except Exception:
        logger.exception("Failed to send renewal OTP SMS")
        return False
