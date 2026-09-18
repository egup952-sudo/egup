from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.content.models import SocialLink

from .models import Event


def list_events(request):
    now = timezone.now()
    upcoming_events = Event.objects.filter(status="PUBLISHED", starts_at__gte=now).order_by("starts_at")
    past_events = Event.objects.filter(status="PUBLISHED", starts_at__lt=now).order_by("-starts_at")
    return render(request, "public/events.html", {
        "upcoming_events": upcoming_events, "past_events": past_events,
        "social_links": SocialLink.objects.filter(is_active=True),
    })


def detail(request, slug):
    event = get_object_or_404(Event, slug=slug, status="PUBLISHED")
    return render(request, "public/event_detail.html", {
        "event": event, "social_links": SocialLink.objects.filter(is_active=True),
    })
