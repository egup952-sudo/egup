"""
Page views for the original frontend wizard. All the actual registration/
payment/renewal LOGIC lives in api.py (JSON endpoints) and is driven by
the original assets/js/membership-registration.js and renewal.js — these
views just serve the original page markup and make sure the CSRF cookie
is set before the wizard's JS starts POSTing.
"""
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.content.models import SocialLink


def _social_links():
    return SocialLink.objects.filter(is_active=True)


@ensure_csrf_cookie
def register(request):
    return render(request, "public/registration.html", {"social_links": _social_links()})


@ensure_csrf_cookie
def renew(request):
    return render(request, "public/renewal.html", {"social_links": _social_links()})
