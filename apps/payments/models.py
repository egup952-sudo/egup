import hashlib
import secrets
import uuid

from django.db import models, transaction
from django.utils import timezone


def _generate_access_token():
    """Cryptographically random, returned to the client ONCE (at payment
    creation) and never again — only its hash is stored server-side
    (same principle as a password). A payment UUID is an identifier, not
    proof of ownership (spec section 6); this token is the actual
    authorization check for status polling and manual submission."""
    return secrets.token_urlsafe(32)


def _hash_access_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


class ApplicationNumberCounter(models.Model):
    """Per-year sequence for Payment.application_number — same race-safe
    pattern as apps.members.MembershipNumberCounter (select_for_update
    inside a transaction), kept separate because a Payment/application
    number is assigned before anyone is a Member, and can outlive a
    registration that never completes."""

    year = models.PositiveIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.year}: {self.last_value}"


def generate_application_number():
    """EGUP-<year>-NNNNNN — human-readable, searchable, unique, and never
    the database primary key. Per the spec: assigned once, used as the
    public reference from the moment a payment is created, independent
    of whether it ever settles."""
    year = timezone.now().year
    with transaction.atomic():
        counter, _ = ApplicationNumberCounter.objects.select_for_update().get_or_create(year=year)
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
        seq = counter.last_value
    return f"EGUP-{year}-{str(seq).zfill(6)}"


class Payment(models.Model):
    """One payment order. State machine per the migration brief section 9:

        PENDING -> PROCESSING -> {PAID | FAILED | CANCELLED | EXPIRED}

    Invalid transitions (e.g. PAID -> PROCESSING) are rejected in
    services.py's transition_status(), not just left to convention — see
    that file for the guard and the compare-and-swap settlement logic that
    closes the race condition documented in Project B's security audit.
    """

    STATUS_CHOICES = [
        ("PENDING", "Pending"),
        ("PROCESSING", "Processing"),
        ("PENDING_VERIFICATION", "Pending manual verification"),
        ("PAID", "Paid"),
        ("REJECTED", "Rejected (manual review failed)"),
        ("SUSPICIOUS", "Flagged as suspicious"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
        ("EXPIRED", "Expired"),
    ]
    PURPOSE_CHOICES = [
        ("REGISTRATION", "New member registration"),
        ("RENEWAL", "Membership renewal"),
        ("EVENT_TICKET", "Event ticket"),
    ]
    PROVIDER_CHOICES = [
        ("PAYHERO", "PayHero (automatic — STK push)"),
        ("MANUAL", "Manual M-Pesa (transaction code, admin-verified)"),
        ("DARAJA", "Daraja (secondary, not yet audited)"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Public, human-readable reference — never the DB primary key/UUID
    # shown to the applicant. "EGUP-2026-000145"-style, same generator
    # pattern as Member.membership_number (see apps.members.models) so an
    # applicant has a reference to quote even before they're a paid
    # member. Assigned once, on creation, never reused.
    application_number = models.CharField(max_length=30, unique=True, db_index=True, blank=True)

    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="PAYHERO")

    registration_intent = models.ForeignKey(
        "members.RegistrationIntent", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments",
    )
    member = models.ForeignKey(
        "members.Member", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments", help_text="Set for renewals; null for a not-yet-settled registration.",
    )

    amount_kes = models.PositiveIntegerField()
    phone_number = models.CharField(max_length=20)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING", db_index=True)

    # PayHero returns two distinct identifiers on STK push — see
    # worker/src/lib/payhero.js verification note, ported here as-is.
    # `provider_reference` is what status-check calls use; `checkout_request_id`
    # is the underlying M-Pesa/Safaricom ID, stored for reference/support only.
    provider_reference = models.CharField(max_length=100, blank=True, db_index=True)
    checkout_request_id = models.CharField(max_length=100, blank=True)
    mpesa_receipt = models.CharField(max_length=50, blank=True)

    # Our own bearer token embedded in the callback URL we register with
    # PayHero, since PayHero does not sign callbacks (confirmed absent,
    # not assumed) — see PayHeroProvider docstring.
    callback_token = models.CharField(max_length=64, unique=True, default=uuid.uuid4, editable=False)

    # Client-side authorization (spec section 6/7): a payment UUID alone
    # is NOT proof of ownership — anyone who can guess/enumerate/observe
    # a UUID could otherwise poll another applicant's payment status or
    # submit a manual payment against it. Only the SHA-256 hash is
    # stored; the raw token is generated once (see
    # services.initiate_payment/initiate_manual_payment) and returned to
    # the client that created the payment, the same way a password reset
    # token would be — never stored or logged in plaintext.
    access_token_hash = models.CharField(max_length=64, blank=True, db_index=True)

    failure_reason = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(check=models.Q(amount_kes__gt=0), name="payment_amount_positive"),
        ]
        indexes = [models.Index(fields=["status", "created_at"])]

    def save(self, *args, **kwargs):
        if not self.application_number:
            self.application_number = generate_application_number()
        super().save(*args, **kwargs)

    def issue_access_token(self) -> str:
        """Generates a new raw token, stores only its hash, and returns
        the raw value — the ONLY time it's ever available in plaintext.
        Call once, at creation."""
        raw_token = _generate_access_token()
        self.access_token_hash = _hash_access_token(raw_token)
        self.save(update_fields=["access_token_hash"])
        return raw_token

    def verify_access_token(self, raw_token: str) -> bool:
        if not raw_token or not self.access_token_hash:
            return False
        return secrets.compare_digest(_hash_access_token(raw_token), self.access_token_hash)

    def __str__(self):
        return f"{self.application_number or self.id} {self.purpose} {self.amount_kes} KES [{self.status}]"

    @property
    def applicant_name(self):
        """Best-available display name: the settled Member if one exists
        yet, otherwise the RegistrationIntent captured at step 1, or the
        name given when booking an event ticket — a payment can exist
        and need to show up in admin lists before any of these fully
        resolve, so this never raises, just falls back."""
        if self.member_id:
            return f"{self.member.other_names} {self.member.surname}".strip()
        if self.registration_intent_id:
            return f"{self.registration_intent.other_names} {self.registration_intent.surname}".strip()
        if self.purpose == "EVENT_TICKET":
            ticket = self.event_ticket.first()
            if ticket:
                return ticket.full_name
        return "—"

    @property
    def applicant_initials(self):
        name = self.applicant_name
        if not name or name == "—":
            return "?"
        parts = [p for p in name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper()


class PaymentCredentials(models.Model):
    """Singleton holding PayHero/Daraja API credentials, settable from the
    admin dashboard instead of requiring shell/server access to edit
    environment variables. Stored ENCRYPTED (see crypto.py) — never
    plaintext at rest, per the brief's explicit requirement. Environment
    variables (settings.PAYHERO_*) remain the fallback when this row is
    empty, so nothing breaks for deployments that prefer env-only config.
    """

    payhero_api_username_enc = models.TextField(blank=True)
    payhero_api_password_enc = models.TextField(blank=True)
    payhero_channel_id_enc = models.TextField(blank=True)
    payhero_callback_base_url = models.CharField(max_length=300, blank=True)  # not secret, plain

    mpesa_consumer_key_enc = models.TextField(blank=True)
    mpesa_consumer_secret_enc = models.TextField(blank=True)
    mpesa_passkey_enc = models.TextField(blank=True)
    mpesa_shortcode_enc = models.TextField(blank=True)
    mpesa_environment = models.CharField(max_length=20, default="sandbox", blank=True)  # not secret, plain

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # ---- transparent encrypt/decrypt accessors ----
    def _get(self, field):
        from .crypto import decrypt_value
        return decrypt_value(getattr(self, field))

    def _set(self, field, value):
        from .crypto import encrypt_value
        setattr(self, field, encrypt_value(value or ""))

    @property
    def payhero_api_username(self): return self._get("payhero_api_username_enc")
    @payhero_api_username.setter
    def payhero_api_username(self, value): self._set("payhero_api_username_enc", value)

    @property
    def payhero_api_password(self): return self._get("payhero_api_password_enc")
    @payhero_api_password.setter
    def payhero_api_password(self, value): self._set("payhero_api_password_enc", value)

    @property
    def payhero_channel_id(self): return self._get("payhero_channel_id_enc")
    @payhero_channel_id.setter
    def payhero_channel_id(self, value): self._set("payhero_channel_id_enc", value)

    @property
    def mpesa_consumer_key(self): return self._get("mpesa_consumer_key_enc")
    @mpesa_consumer_key.setter
    def mpesa_consumer_key(self, value): self._set("mpesa_consumer_key_enc", value)

    @property
    def mpesa_consumer_secret(self): return self._get("mpesa_consumer_secret_enc")
    @mpesa_consumer_secret.setter
    def mpesa_consumer_secret(self, value): self._set("mpesa_consumer_secret_enc", value)

    @property
    def mpesa_passkey(self): return self._get("mpesa_passkey_enc")
    @mpesa_passkey.setter
    def mpesa_passkey(self, value): self._set("mpesa_passkey_enc", value)

    @property
    def mpesa_shortcode(self): return self._get("mpesa_shortcode_enc")
    @mpesa_shortcode.setter
    def mpesa_shortcode(self, value): self._set("mpesa_shortcode_enc", value)


class PaymentAttempt(models.Model):
    """Every STK push attempt and every status-check call, kept for
    support/debugging and to detect abuse (e.g. someone spamming STK
    pushes for one payment — see services.py's rate check)."""

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="attempts")
    kind = models.CharField(
        max_length=20,
        choices=[("STK_PUSH", "STK push initiated"), ("STATUS_CHECK", "Status check"), ("CALLBACK", "Callback received")],
    )
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    succeeded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


def _manual_payment_screenshot_path(instance, filename):
    import os
    import uuid as _uuid

    ext = os.path.splitext(filename)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".bin"
    return f"manual_payment_screenshots/{_uuid.uuid4().hex}{ext}"


class ManualPaymentSubmission(models.Model):
    """The applicant's claim that they paid via M-Pesa, submitted for
    admin review. Deliberately NEVER settles a Payment by itself —
    submitting this only moves the linked Payment to
    PENDING_VERIFICATION (see services.py:submit_manual_payment).
    Only an admin action (verify_manual_payment /
    reject_manual_payment) can move it to PAID or REJECTED. This is the
    "critical business rule" from the spec: a user-entered M-Pesa code
    is never, by itself, sufficient to mark a payment PAID.
    """

    CONFIDENCE_CHOICES = [
        ("HIGH", "High confidence — reference/amount/uniqueness all match"),
        ("MEDIUM", "Medium confidence — needs a human look"),
        ("LOW", "Low confidence — likely wrong or reused"),
    ]

    # ForeignKey, NOT OneToOne — a rejected applicant must be able to
    # submit a corrected payment (spec: "Manual Payment Resubmission
    # Bug"). Each attempt is its own row; nothing is ever overwritten.
    # The Payment's CURRENT state is always the latest attempt, found via
    # payment.manual_submissions.order_by('-submitted_at').first() —
    # see services.get_latest_manual_submission().
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="manual_submissions")

    # Fraud prevention (spec section 15/22): a transaction code can only
    # ever be submitted once across the whole system. This is enforced
    # at the DATABASE level (unique=True), not just in application code —
    # a duplicate submission attempt fails atomically, it can't race past
    # a check-then-insert gap.
    transaction_code = models.CharField(max_length=40, unique=True, db_index=True)
    phone_number_used = models.CharField(max_length=20)
    amount_submitted = models.PositiveIntegerField()
    payment_date = models.DateField()
    screenshot = models.ImageField(upload_to=_manual_payment_screenshot_path, null=True, blank=True)

    confidence = models.CharField(max_length=10, choices=CONFIDENCE_CHOICES, default="MEDIUM")
    confidence_notes = models.CharField(max_length=255, blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)

    VERIFICATION_CHOICES = [
        ("PENDING", "Pending"),
        ("VERIFIED", "Verified — payment marked PAID"),
        ("REJECTED", "Rejected"),
        ("SUSPICIOUS", "Flagged as suspicious"),
    ]
    verification_status = models.CharField(max_length=12, choices=VERIFICATION_CHOICES, default="PENDING")
    verified_by = models.ForeignKey(
        "auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [models.Index(fields=["verification_status", "submitted_at"])]

    def __str__(self):
        return f"{self.transaction_code} for {self.payment.application_number} [{self.verification_status}]"
