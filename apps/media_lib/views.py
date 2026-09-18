from django.shortcuts import render

from apps.content.models import SocialLink

from .models import MediaAsset


def gallery(request):
    images = MediaAsset.objects.filter(category="GALLERY", is_published=True)
    return render(request, "public/gallery.html", {
        "images": images, "social_links": SocialLink.objects.filter(is_active=True),
    })
