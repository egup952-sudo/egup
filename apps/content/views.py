from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from apps.announcements.models import Announcement
from apps.events.models import Event
from apps.media_lib.models import MediaAsset

from .models import HeroSlide, Page, SiteSetting, SocialLink


def _social_links():
    return SocialLink.objects.filter(is_active=True)


def home(request):
    from apps.members.models import Member

    slides = HeroSlide.objects.filter(is_active=True).select_related("image")
    upcoming_events = Event.objects.filter(status="PUBLISHED").order_by("starts_at")[:3]
    gallery_highlights = MediaAsset.objects.filter(category="GALLERY", is_published=True, is_featured=True)[:6]
    if not gallery_highlights:
        gallery_highlights = MediaAsset.objects.filter(category="GALLERY", is_published=True)[:6]
    announcements = [a for a in Announcement.objects.filter(status="PUBLISHED") if a.is_currently_visible()][:3]

    # Real counts only — no invented numbers (brief section 13's "no
    # hardcoded/fake numbers" principle extended to public-facing stats).
    stats = {
        "total_members": Member.objects.filter(is_active=True).count(),
        "events_held": Event.objects.filter(status="PUBLISHED").count(),
        "counties_reached": Member.objects.filter(is_active=True).values("county").distinct().count(),
    }
    next_event = Event.objects.filter(status="PUBLISHED", starts_at__gte=timezone.now()).order_by("starts_at").first()

    return render(request, "public/home.html", {
        "slides": slides, "upcoming_events": upcoming_events,
        "gallery_highlights": gallery_highlights, "announcements": announcements,
        "social_links": _social_links(), "stats": stats, "next_event": next_event,
    })


def about(request):
    return render(request, "public/about.html", {"social_links": _social_links()})


def programs(request):
    return render(request, "public/programs.html", {"social_links": _social_links()})


@ensure_csrf_cookie
def contact(request):
    settings_obj = SiteSetting.get_solo()
    return render(request, "public/contact.html", {"settings": settings_obj, "social_links": _social_links()})


def how_to_pay(request):
    from apps.members.models import SystemSettings
    from apps.payments.providers import is_automatic_payment_available, is_manual_payment_available

    settings_obj = SystemSettings.get_solo()
    return render(request, "public/how_to_pay.html", {
        "settings": settings_obj, "social_links": _social_links(),
        "automatic_available": is_automatic_payment_available(),
        "manual_available": is_manual_payment_available(),
    })


def privacy(request):
    settings_obj = SiteSetting.get_solo()
    return render(request, "public/legal.html", {
        "title": "Privacy Policy", "body": settings_obj.privacy_policy_content,
        "social_links": _social_links(),
    })


def terms(request):
    settings_obj = SiteSetting.get_solo()
    return render(request, "public/legal.html", {
        "title": "Terms of Use", "body": settings_obj.terms_content,
        "social_links": _social_links(),
    })


def dynamic_page(request, slug):
    page = get_object_or_404(Page, slug=slug, status="PUBLISHED")
    blocks = page.blocks.select_related("image").all()
    return render(request, "public/page.html", {"page": page, "blocks": blocks, "social_links": _social_links()})
