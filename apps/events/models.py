import uuid as _uuid

from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify


class Event(models.Model):
    STATUS_CHOICES = [("DRAFT", "Draft"), ("PUBLISHED", "Published"), ("ARCHIVED", "Archived")]

    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    image = models.ForeignKey(
        "media_lib.MediaAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    registration_url = models.URLField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    is_featured = models.BooleanField(default=False)

    # Ticket booking — off by default (brief: "not every event needs a
    # ticket booking"). When on, the public event page shows a booking
    # flow instead of/alongside registration_url; when off, none of this
    # is shown or reachable at all — the API also rejects booking
    # attempts against an event with requires_ticket=False, not just the
    # template.
    requires_ticket = models.BooleanField(
        default=False, help_text="Show a ticket booking flow on this event's page."
    )
    ticket_price_kes = models.PositiveIntegerField(
        default=0, help_text="0 = free ticket (RSVP only, no payment step)."
    )
    ticket_capacity = models.PositiveIntegerField(
        null=True, blank=True, help_text="Leave blank for unlimited tickets."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        indexes = [models.Index(fields=["status", "starts_at"])]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:220]
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def tickets_booked_count(self):
        """Confirmed + still-payable tickets count against capacity — a
        PENDING_PAYMENT ticket holds its place for a short window (same
        reasoning as Payment itself) so two people can't both be told
        there's a spot for the last seat."""
        return self.tickets.filter(status__in=["CONFIRMED", "PENDING_PAYMENT"]).aggregate(
            total=models.Sum("quantity")
        )["total"] or 0

    @property
    def tickets_remaining(self):
        if self.ticket_capacity is None:
            return None
        return max(0, self.ticket_capacity - self.tickets_booked_count)

    @property
    def is_sold_out(self):
        return self.ticket_capacity is not None and self.tickets_remaining == 0


def _generate_ticket_reference():
    """EGUP-TKT-<year>-NNNNNN — same human-readable, race-safe pattern as
    Payment.application_number and Member.membership_number (see those
    for why: select_for_update inside a transaction, never the DB PK)."""
    year = timezone.now().year
    with transaction.atomic():
        counter, _ = TicketReferenceCounter.objects.select_for_update().get_or_create(year=year)
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
        seq = counter.last_value
    return f"EGUP-TKT-{year}-{str(seq).zfill(6)}"


class TicketReferenceCounter(models.Model):
    year = models.PositiveIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.year}: {self.last_value}"


class EventTicket(models.Model):
    """One booking against an Event with requires_ticket=True. Mirrors
    the Payment/RegistrationIntent split: this row exists the moment
    someone starts booking, independent of whether payment (if any) ever
    completes — so a booking can be traced/cleaned up even if abandoned."""

    STATUS_CHOICES = [
        ("PENDING_PAYMENT", "Pending payment"),
        ("CONFIRMED", "Confirmed"),
        ("CANCELLED", "Cancelled"),
    ]

    id = models.UUIDField(primary_key=True, default=_uuid.uuid4, editable=False)

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="tickets")
    reference_code = models.CharField(max_length=30, unique=True, db_index=True, blank=True)

    full_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20)
    quantity = models.PositiveIntegerField(default=1)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING_PAYMENT", db_index=True)

    # Null for a free ticket — there is nothing to pay, so nothing to
    # link. Set for a paid ticket, reusing the SAME Payment model/STK
    # push/manual-PayBill machinery already built for membership, rather
    # than a second, duplicate payment system (purpose="EVENT_TICKET").
    payment = models.ForeignKey(
        "payments.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="event_ticket"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event", "status"])]

    def save(self, *args, **kwargs):
        if not self.reference_code:
            self.reference_code = _generate_ticket_reference()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_code} ({self.full_name}) x{self.quantity} [{self.status}]"
