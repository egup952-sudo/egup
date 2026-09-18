"""
Backend-enforced abuse protection for payment endpoints (spec sections
8/16). Frontend button-disabling is explicitly NOT sufficient per the
spec — these checks run server-side, on every request, regardless of
what the client does.

Uses Django's cache framework (already configured — see CACHES in
settings.py). NOTE: the default LocMemCache is per-process, so with
multiple gunicorn workers in production these limits are enforced
per-worker, not globally — a real limitation, not hidden here. For a
multi-worker production deployment, point CACHES at Redis/Memcached
(shared across processes) to make this actually global; the rate-limit
logic itself doesn't change.
"""
from django.core.cache import cache

MAX_INITIATIONS_PER_PHONE_PER_WINDOW = 3
INITIATION_WINDOW_SECONDS = 600  # 10 minutes

MAX_MANUAL_SUBMISSIONS_PER_PAYMENT = 5
MANUAL_SUBMIT_COOLDOWN_SECONDS = 30  # between attempts on the SAME payment


def check_payment_initiation_allowed(phone_number: str):
    """Returns (allowed, retry_after_seconds). A phone number can only
    initiate a handful of payments in a 10-minute window — covers both
    'user mashing the pay button' and a scripted abuse attempt, since
    both hit this the same way."""
    key = f"payment_init_count:{phone_number}"
    count = cache.get(key, 0)
    if count >= MAX_INITIATIONS_PER_PHONE_PER_WINDOW:
        ttl = cache.ttl(key) if hasattr(cache, "ttl") else INITIATION_WINDOW_SECONDS
        return False, ttl or INITIATION_WINDOW_SECONDS
    cache.set(key, count + 1, timeout=INITIATION_WINDOW_SECONDS)
    return True, 0


def check_existing_active_payment(*, registration_intent=None, member=None):
    """Spec section 8: 'one active payment attempt per registration.' If
    there's already a PENDING/PROCESSING/PENDING_VERIFICATION payment for
    this same registration intent or member, don't create a second one —
    return it instead so the caller can resume it."""
    from .models import Payment

    qs = Payment.objects.filter(status__in=["PENDING", "PROCESSING", "PENDING_VERIFICATION"])
    if registration_intent is not None:
        qs = qs.filter(registration_intent=registration_intent)
    elif member is not None:
        qs = qs.filter(member=member)
    else:
        return None
    return qs.order_by("-created_at").first()


def check_manual_submission_cooldown(payment_id):
    """Prevents rapid repeated manual-payment submissions against the
    SAME payment (double-click, retry-spam) — separate from the
    duplicate-transaction-code DB constraint, which stops REUSE of a
    code but not repeated submission attempts in general."""
    key = f"manual_submit_cooldown:{payment_id}"
    if cache.get(key):
        return False, MANUAL_SUBMIT_COOLDOWN_SECONDS
    cache.set(key, True, timeout=MANUAL_SUBMIT_COOLDOWN_SECONDS)
    return True, 0
