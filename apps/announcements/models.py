from django.db import models


class Announcement(models.Model):
    STATUS_CHOICES = [("DRAFT", "Draft"), ("PUBLISHED", "Published"), ("ARCHIVED", "Archived")]

    title = models.CharField(max_length=200)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    is_featured = models.BooleanField(default=False)
    publish_at = models.DateTimeField(
        null=True, blank=True, help_text="Leave blank to publish immediately on save when status=PUBLISHED."
    )
    expire_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "publish_at", "expire_at"])]

    def __str__(self):
        return self.title

    def is_currently_visible(self) -> bool:
        from django.utils import timezone

        if self.status != "PUBLISHED":
            return False
        now = timezone.now()
        if self.publish_at and self.publish_at > now:
            return False
        if self.expire_at and self.expire_at < now:
            return False
        return True
