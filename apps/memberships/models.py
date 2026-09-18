from django.db import models
from django.utils import timezone

from apps.members.models import Member


class Membership(models.Model):
    """One row per membership PERIOD, not one row per member.

    A renewal creates a NEW Membership row rather than mutating the
    previous one's expiry date in place — this is what the brief's section
    12 requires and is exactly the pattern Project B's schema already used
    (member -> membership #1, #2, #3 ...). Whoever renders "current status"
    for a member does so by reading the latest row, never by overwriting
    history.
    """

    STATUS_CHOICES = [
        ("ACTIVE", "Active"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
    ]
    SOURCE_CHOICES = [
        ("REGISTRATION", "Initial registration"),
        ("RENEWAL", "Renewal"),
        ("ADMIN_GRANT", "Manually granted by an admin"),
    ]

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="memberships")
    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="memberships",
        help_text="The settled payment that created this period. Null only for ADMIN_GRANT.",
    )
    start_date = models.DateField()
    expiry_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    created_by_admin = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Set only when source=ADMIN_GRANT.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        indexes = [models.Index(fields=["member", "-start_date"])]

    def __str__(self):
        return f"{self.member.membership_number}: {self.start_date} - {self.expiry_date} ({self.status})"

    def is_currently_active(self) -> bool:
        return self.status == "ACTIVE" and self.expiry_date >= timezone.now().date()

    @classmethod
    def current_for(cls, member: Member):
        """The member's latest membership row, i.e. their current status."""
        return cls.objects.filter(member=member).order_by("-start_date").first()
