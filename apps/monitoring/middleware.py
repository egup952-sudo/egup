"""
Ported from Project A's membership/middleware.py, near-verbatim — this was
already solid. Two changes:

1. Protected path updated to settings.ADMIN_ROUTE_PREFIX (a discreet,
   non-guessable path — brief section 22) instead of the guessable
   '/admin-portal/'.
2. IP resolution now goes through apps.monitoring.ip_utils.get_client_ip,
   which trusts Cloudflare's CF-Connecting-IP instead of a raw,
   client-spoofable X-Forwarded-For (brief section 27).
"""
from django.conf import settings
from django.http import HttpResponseForbidden

from .ip_utils import get_client_ip
from .rate_limit import is_ip_blocked


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Frame-Options"] = "DENY"
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            # Bootstrap Icons is loaded site-wide (every <i class="bi bi-*">
            # on every public AND admin page) as a stylesheet from
            # cdn.jsdelivr.net, which in turn loads its own icon font from
            # the same host. Neither style-src nor font-src previously
            # allowed jsdelivr — only script-src did — so the browser was
            # silently refusing to load bootstrap-icons.css and its font
            # file at all. Every single icon on the entire site has been
            # invisible because of this, not because of anything wrong in
            # the templates that use them (this is almost certainly the
            # real explanation for the "social media icons don't show up"
            # report from earlier — it was never the footer logic).
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://*.tile.openstreetmap.org; "
            "frame-src 'self' https://www.openstreetmap.org; "
            "connect-src 'self';"
        )
        if not settings.DEBUG:
            response["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response


class IPBlockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.protected_paths = [getattr(settings, "ADMIN_ROUTE_PREFIX", "/dashboard/")]

    def __call__(self, request):
        path = request.path_info
        if any(path.startswith(p) for p in self.protected_paths):
            ip = get_client_ip(request)
            blocked, mins = is_ip_blocked(ip)
            if blocked:
                msg = f"Access temporarily blocked. Try again in {mins} minutes." if mins else "Access denied."
                return HttpResponseForbidden(
                    f'<html><body style="font-family:sans-serif;padding:40px;background:#1a472a;color:#fff;">'
                    f"<h2>Access Blocked</h2><p>{msg}</p></body></html>"
                )
        return self.get_response(request)
