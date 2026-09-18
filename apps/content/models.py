"""
CMS models. Design constraint from the brief (sections 15-16): admins edit
CONTENT, never CSS/JS/templates. Rich text is stored as plain text/markdown
and rendered through a whitelisted-tag sanitizer (see blocks.py) — never
raw HTML from an admin textarea straight into the page.
"""
from django.db import models

from .default_legal_content import PRIVACY_POLICY_DEFAULT, TERMS_OF_USE_DEFAULT


def _default_privacy():
    return PRIVACY_POLICY_DEFAULT


def _default_terms():
    return TERMS_OF_USE_DEFAULT


class HeroSlide(models.Model):
    """Multiple slides supported; publishing/reordering never deletes or
    overwrites another slide's image — each slide is its own row/asset
    (brief section 17)."""

    title = models.CharField(max_length=200)
    subtitle = models.TextField(blank=True)
    image = models.ForeignKey("media_lib.MediaAsset", on_delete=models.PROTECT, related_name="hero_slides")
    cta_label = models.CharField(max_length=100, blank=True)
    cta_url = models.CharField(max_length=300, blank=True)
    secondary_cta_label = models.CharField(max_length=100, blank=True)
    secondary_cta_url = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-created_at"]

    def __str__(self):
        return self.title


BLOCK_TYPE_CHOICES = [
    ("heading", "Heading"),
    ("paragraph", "Paragraph"),
    ("image", "Image"),
    ("two_column", "Two-column content"),
    ("cta", "Call to action"),
    ("gallery", "Gallery"),
    ("quote", "Quote"),
    ("contact", "Contact section"),
]


class Page(models.Model):
    """Admin-creatable dynamic page. Publishing makes it live at
    /pages/<slug>/ automatically (brief section 16) — no template edit,
    no deploy needed."""

    STATUS_CHOICES = [("DRAFT", "Draft"), ("PUBLISHED", "Published"), ("ARCHIVED", "Archived")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    seo_title = models.CharField(max_length=200, blank=True)
    seo_description = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title


class PageBlock(models.Model):
    """One structured content block within a Page. `content` holds
    plain/markdown text ONLY for text-bearing block types — never raw
    HTML — rendered through blocks.py's sanitizer at display time."""

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="blocks")
    block_type = models.CharField(max_length=20, choices=BLOCK_TYPE_CHOICES)
    content = models.TextField(blank=True)
    image = models.ForeignKey(
        "media_lib.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="page_blocks"
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order"]


class SocialLink(models.Model):
    platform = models.CharField(max_length=50)
    url = models.URLField()
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order"]

    def __str__(self):
        return self.platform


class SiteSetting(models.Model):
    """Singleton for footer contact info, org address, etc. — content an
    admin should be able to edit without a code change."""

    contact_email = models.EmailField(blank=True, default="egupa@gmail.com")
    contact_phone = models.CharField(max_length=30, blank=True, default="+254725077288")
    address = models.CharField(max_length=255, blank=True, default="Narok Town, Kenya")
    privacy_policy_content = models.TextField(blank=True, default=_default_privacy)
    terms_content = models.TextField(blank=True, default=_default_terms)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ContactMessage(models.Model):
    """Submissions from the public contact form (contact.html)."""

    name = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} <{self.email}>: {self.subject or self.message[:40]}"
