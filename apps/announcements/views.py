from django.shortcuts import render

from apps.content.models import SocialLink

from .models import Announcement


def list_announcements(request):
    announcements = [a for a in Announcement.objects.filter(status="PUBLISHED") if a.is_currently_visible()]
    return render(request, "public/announcements.html", {
        "announcements": announcements, "social_links": SocialLink.objects.filter(is_active=True),
    })
