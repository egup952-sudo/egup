from datetime import timedelta

from django.utils import timezone

from .ip_utils import get_client_ip  # re-exported for callers that used to import from membership.rate_limit
from .models import IPBlocklist, LoginAttempt

MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 30
WINDOW_MINUTES = 15


def is_ip_blocked(ip):
    block = IPBlocklist.objects.filter(ip_address=ip, unblocked=False).order_by("-blocked_at").first()
    if block and block.is_active:
        if block.is_permanent:
            return True, None
        remaining = max(1, int((block.blocked_until - timezone.now()).total_seconds() // 60))
        return True, remaining
    return False, 0


def count_recent_failures(ip, username, window_minutes=WINDOW_MINUTES):
    since = timezone.now() - timedelta(minutes=window_minutes)
    return LoginAttempt.objects.filter(ip_address=ip, success=False, timestamp__gte=since).count()


def record_attempt(request, username, success, reason=""):
    ip = get_client_ip(request)
    ua = request.META.get("HTTP_USER_AGENT", "")[:400]
    LoginAttempt.objects.create(ip_address=ip, username_tried=username, success=success, user_agent=ua, reason=reason)
    if not success:
        failures = count_recent_failures(ip, username)
        if failures >= MAX_ATTEMPTS:
            _auto_block_ip(ip, failures)


def _auto_block_ip(ip, failure_count):
    IPBlocklist.objects.create(
        ip_address=ip,
        reason=f"Auto-blocked after {failure_count} failed login attempts",
        blocked_until=timezone.now() + timedelta(minutes=LOCKOUT_MINUTES),
    )
