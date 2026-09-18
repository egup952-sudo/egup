from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Append-only log of sensitive actions (brief section 24).

    Deliberately has no update path in application code — rows are only
    ever created, never edited. Nothing here stores secrets (no tokens,
    no full card/M-Pesa numbers) — only what/who/when/object metadata.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_actions",
        help_text="Null for system/unauthenticated actions (e.g. a payment callback).",
    )
    action = models.CharField(
        max_length=100,
        help_text="e.g. 'login', 'failed_login', 'member.create', 'payment.settle', 'content.publish'",
    )
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.action} by {self.actor_id} @ {self.created_at:%Y-%m-%d %H:%M}"


def log_action(action, actor=None, obj=None, request=None, **metadata):
    """Single helper every app calls instead of creating AuditLog rows
    directly, so the shape stays consistent everywhere."""
    ip = None
    if request is not None:
        ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR"))
        if ip and "," in ip:
            # Only trust the first hop if TRUSTED_PROXY middleware has
            # already validated/stripped this header — see apps/monitoring
            # /middleware.py. Never trust an arbitrary client-supplied XFF.
            ip = ip.split(",")[0].strip()
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
        metadata=metadata,
        ip_address=ip,
    )
