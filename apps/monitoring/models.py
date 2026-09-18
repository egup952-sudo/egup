from django.db import models
from django.utils import timezone


class LoginAttempt(models.Model):
    ip_address = models.GenericIPAddressField()
    username_tried = models.CharField(max_length=150, blank=True)
    success = models.BooleanField(default=False)
    user_agent = models.CharField(max_length=400, blank=True)
    reason = models.CharField(max_length=200, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["ip_address", "success", "timestamp"])]


class IPBlocklist(models.Model):
    ip_address = models.GenericIPAddressField()
    reason = models.CharField(max_length=255, blank=True)
    blocked_at = models.DateTimeField(auto_now_add=True)
    blocked_until = models.DateTimeField(null=True, blank=True)
    is_permanent = models.BooleanField(default=False)
    unblocked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-blocked_at"]

    @property
    def is_active(self) -> bool:
        if self.unblocked:
            return False
        if self.is_permanent:
            return True
        return bool(self.blocked_until and self.blocked_until > timezone.now())
