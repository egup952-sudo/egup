from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.content.models import Page
from apps.events.models import Event


class StaticViewSitemap(Sitemap):
    """The fixed public pages — priority reflects how central each is to
    the site, not an arbitrary guess (home highest, legal pages lowest)."""

    changefreq = "weekly"

    def items(self):
        return ["content:home", "content:about", "content:programs", "content:contact",
                "events:list", "announcements:list", "media_lib:gallery",
                "members:register", "members:renew"]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return {"content:home": 1.0, "members:register": 0.9, "members:renew": 0.7}.get(item, 0.6)


class EventSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Event.objects.filter(status="PUBLISHED")

    def location(self, obj):
        return f"/events/{obj.slug}.html"

    def lastmod(self, obj):
        return obj.updated_at


class DynamicPageSitemap(Sitemap):
    changefreq = "monthly"
    priority = 0.5

    def items(self):
        return Page.objects.filter(status="PUBLISHED")

    def location(self, obj):
        return f"/pages/{obj.slug}.html"

    def lastmod(self, obj):
        return obj.updated_at


sitemaps = {
    "static": StaticViewSitemap,
    "events": EventSitemap,
    "pages": DynamicPageSitemap,
}
