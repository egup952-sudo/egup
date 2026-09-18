"""
Trusted client-IP resolution.

Project A's original get_client_ip() took the first entry of
X-Forwarded-For unconditionally. Behind Cloudflare, an attacker's own
request can include an arbitrary X-Forwarded-For header — if the web
server in front of Django doesn't strip/overwrite it, the attacker
controls what Django thinks their IP is, defeating rate limiting and the
audit trail (exactly the risk called out in the migration brief section 27).

Cloudflare sets `CF-Connecting-IP` itself, overwriting any client-supplied
copy of that header at Cloudflare's edge — it's the correct signal to use.
X-Forwarded-For is only used as a fallback for local/dev environments
where there is no Cloudflare in front, and is clearly documented as such.

IMPORTANT: this guarantee (CF-Connecting-IP being trustworthy) only holds
if Django is NOT directly reachable from the internet — the origin server
must be firewalled so only Cloudflare's IP ranges can reach it. Document
this requirement in DEPLOYMENT.md; it's an infrastructure requirement this
code cannot enforce by itself.
"""
from django.conf import settings


def get_client_ip(request) -> str:
    if getattr(settings, "BEHIND_CLOUDFLARE", True):
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            return cf_ip.strip()
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")
