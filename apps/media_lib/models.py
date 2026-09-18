import os
import uuid

from django.conf import settings
from django.db import models


def _safe_upload_path(instance, filename):
    """Random filename, original extension only — never the user-supplied
    name verbatim (path traversal / overwrite-by-same-name prevention,
    brief section 28)."""
    ext = os.path.splitext(filename)[1].lower()
    allowed_ext = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    if ext not in allowed_ext:
        ext = ".bin"
    return f"gallery/{uuid.uuid4().hex}{ext}"


class MediaAsset(models.Model):
    """One row per uploaded image. This IS the fix for the 'uploading a
    new image deletes/replaces an old one' bug described in the brief
    (section 20) — every upload is its own row and its own file; nothing
    here ever overwrites another asset's `file` field.
    """

    CATEGORY_CHOICES = [
        ("GALLERY", "Gallery"),
        ("HERO", "Hero slide"),
        ("EVENT", "Event image"),
        ("PAGE_BLOCK", "Page block image"),
        ("OTHER", "Other"),
    ]

    file = models.ImageField(upload_to=_safe_upload_path)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="GALLERY")
    caption = models.CharField(max_length=255, blank=True)
    alt_text = models.CharField(max_length=255, blank=True)
    is_featured = models.BooleanField(default=False)
    is_published = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="uploaded_media"
    )
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-created_at"]
        indexes = [models.Index(fields=["category", "is_published"])]

    def __str__(self):
        return self.caption or self.file.name

    def delete(self, *args, **kwargs):
        """Deleting THIS row/file must never touch any other MediaAsset's
        file — Django's default ImageField behaviour already satisfies
        this since each instance owns its own `file` path, but it's
        called out here so nobody 'optimizes' this into a shared-field
        design later."""
        storage, path = self.file.storage, self.file.name
        super().delete(*args, **kwargs)
        if path:
            storage.delete(path)
