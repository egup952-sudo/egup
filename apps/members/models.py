"""
Member identity + registration, matching the ORIGINAL frontend wizard's
actual field set (registration.html steps 1-3: personal, profession/
skills/department, referee) — not a simplified re-guess of what a
registration form "should" have. See PROGRESS.md for the correction that
led to this rewrite.

    RegistrationIntent --(payment settles)--> Member + Membership (apps.memberships)
"""
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone


class SystemSettings(models.Model):
    membership_number_prefix = models.CharField(max_length=10, default="EGUP")
    membership_number_width = models.PositiveSmallIntegerField(default=6)
    membership_fee_kes = models.PositiveIntegerField(default=200)  # original site: KES 200
    renewal_fee_kes = models.PositiveIntegerField(default=100)     # original site: KES 100

    # ---- Payment mode configuration (dual payment system) ----
    # Operational, editable settings — NOT secret, so they live here
    # rather than in apps.payments.PaymentCredentials (which is
    # encrypted). An admin toggles these from Settings > Payments.
    automatic_payment_enabled = models.BooleanField(
        default=False,
        help_text="Show 'Pay with M-Pesa' (STK push via PayHero) as an option. "
                   "Requires PayHero credentials to be configured (env vars or "
                   "Finance > Payment Credentials) — see is_automatic_payment_available().",
    )
    manual_payment_enabled = models.BooleanField(
        default=True,
        help_text="Show 'Pay manually' (M-Pesa PayBill/Till + transaction code, admin-verified) as an option.",
    )
    manual_payment_paybill = models.CharField(
        max_length=20, blank=True, default="247247",
        help_text="Official EGUP M-Pesa PayBill number.",
    )
    manual_payment_till = models.CharField(max_length=20, blank=True, help_text="Leave blank if using a PayBill instead.")
    manual_payment_account_note = models.CharField(
        max_length=255, blank=True, default="100658",
        help_text="Official EGUP M-Pesa account number, shown to applicants exactly as entered here.",
    )
    manual_payment_instructions = models.TextField(
        blank=True,
        help_text="Extra instructions shown above the manual payment form, e.g. business name confirmation text.",
    )
    manual_payment_screenshot_required = models.BooleanField(default=False)

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MembershipNumberCounter(models.Model):
    year = models.PositiveIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.year}: {self.last_value}"


def generate_membership_number():
    """EGUP-<year>-NNNNNN. Ported from Project A (race-safe via
    select_for_update inside a transaction)."""
    year = timezone.now().year
    settings_obj = SystemSettings.get_solo()
    prefix = settings_obj.membership_number_prefix or "EGUP"
    width = settings_obj.membership_number_width or 6
    with transaction.atomic():
        counter, _ = MembershipNumberCounter.objects.select_for_update().get_or_create(year=year)
        counter.last_value += 1
        counter.save(update_fields=["last_value"])
        seq = counter.last_value
    return f"{prefix}-{year}-{str(seq).zfill(width)}"


# ---------------------------------------------------------------------
# Reference data — these power the registration form's dropdowns/
# checklists (assets/js/reference-data.js originally read these from
# Supabase tables `counties`/`churches`/`professions`/`skills`/
# `departments`; Project A's Django app already had Skill/Profession/
# Department models). Admin-manageable, matching brief section 13's
# "no hardcoded data admins can't change" spirit.
# ---------------------------------------------------------------------

class County(models.Model):
    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Counties"

    def __str__(self):
        return self.name


class Church(models.Model):
    name = models.CharField(max_length=150, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Churches"

    def __str__(self):
        return self.name


class Skill(models.Model):
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Profession(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


GENDER_CHOICES = [("MALE", "Male"), ("FEMALE", "Female")]


class RegistrationIntent(models.Model):
    """What the public registration wizard actually submits (steps 1-3),
    before payment settles. Fields match registration.html verbatim —
    surname/other_names, not a single full_name; county/church as FKs to
    the reference tables above, not free text; optional profession/
    experience/gift/skills/departments; optional referee block."""

    STATUS_CHOICES = [
        ("PENDING_PAYMENT", "Pending payment"),
        ("SETTLED", "Settled (member created)"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
    ]

    # Step 1: Personal
    surname = models.CharField(max_length=100)
    other_names = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    county = models.ForeignKey(County, on_delete=models.PROTECT, related_name="registration_intents")
    location = models.CharField(max_length=150, blank=True)
    home_town = models.CharField(max_length=150, blank=True)
    religion = models.CharField(max_length=100, blank=True)
    church = models.ForeignKey(
        Church, on_delete=models.SET_NULL, null=True, blank=True, related_name="registration_intents"
    )

    # Step 2: Profession / skills / department
    profession = models.ForeignKey(
        Profession, on_delete=models.SET_NULL, null=True, blank=True, related_name="registration_intents"
    )
    experience = models.CharField(max_length=200, blank=True)
    gift = models.CharField(max_length=150, blank=True)
    skills = models.ManyToManyField(Skill, blank=True, related_name="registration_intents")
    departments = models.ManyToManyField(Department, blank=True, related_name="registration_intents")

    # Step 3: Referee / next of kin
    referee_name = models.CharField(max_length=150, blank=True)
    referee_phone = models.CharField(max_length=20, blank=True)
    referee_location = models.CharField(max_length=150, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING_PAYMENT")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.surname} {self.other_names} ({self.status})"

    @property
    def full_name(self):
        return f"{self.surname} {self.other_names}".strip()


class Member(models.Model):
    """A real, paid-and-verified member. Created only by the payment
    settlement transaction in apps.payments."""

    membership_number = models.CharField(max_length=30, unique=True, db_index=True)
    surname = models.CharField(max_length=100)
    other_names = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True)
    county = models.ForeignKey(County, on_delete=models.PROTECT, related_name="members")
    location = models.CharField(max_length=150, blank=True)
    home_town = models.CharField(max_length=150, blank=True)
    religion = models.CharField(max_length=100, blank=True)
    church = models.ForeignKey(Church, on_delete=models.SET_NULL, null=True, blank=True, related_name="members")
    profession = models.ForeignKey(
        Profession, on_delete=models.SET_NULL, null=True, blank=True, related_name="members"
    )
    experience = models.CharField(max_length=200, blank=True)
    gift = models.CharField(max_length=150, blank=True)
    skills = models.ManyToManyField(Skill, blank=True, related_name="members")
    departments = models.ManyToManyField(Department, blank=True, related_name="members")
    referee_name = models.CharField(max_length=150, blank=True)
    referee_phone = models.CharField(max_length=20, blank=True)
    referee_location = models.CharField(max_length=150, blank=True)

    registration_intent = models.OneToOneField(
        RegistrationIntent, on_delete=models.SET_NULL, null=True, blank=True, related_name="member"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.membership_number} - {self.full_name}"

    @property
    def full_name(self):
        return f"{self.surname} {self.other_names}".strip()


def _generate_otp_code():
    """6-digit OTP using a cryptographically secure RNG (secrets, not
    random) — per spec section 3's explicit "cryptographically secure
    random generation" / "do not use predictable OTP generation"."""
    import secrets

    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp_code(code: str) -> str:
    """Same reasoning as Payment's access-token hashing (see
    apps.payments.models): store a hash, not the plaintext code, so a
    database read (backup, leaked dump, curious insider with DB access)
    doesn't hand over live OTPs. Uses Django's PBKDF2 password hasher —
    an OTP is short and numeric (much lower entropy than a real
    password), so a slow, salted hash matters here specifically to
    resist offline brute force of a stolen hash, not just for show."""
    from django.contrib.auth.hashers import make_password

    return make_password(code)


class RenewalOTP(models.Model):
    """Proof that whoever is renewing controls the member's registered
    phone — a membership number alone is NOT authentication (spec
    section 3's central point: it's often sequential/guessable, and
    renewal.html/renewal.js's OLD flow let anyone who typed/guessed one
    start a real payment against a stranger's phone number). This row
    is single-use and short-lived; RenewalAuthorization (below) is the
    actual "you may now renew" credential, issued only after this is
    verified.
    """

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="renewal_otps")
    code_hash = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    consumed = models.BooleanField(default=False)
    request_ip = models.GenericIPAddressField(null=True, blank=True)

    MAX_ATTEMPTS = 5
    TTL_SECONDS = 300  # 5 minutes

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["member", "consumed", "expires_at"])]

    def is_valid(self):
        return not self.consumed and self.attempts < self.MAX_ATTEMPTS and timezone.now() < self.expires_at

    def check_code(self, raw_code: str) -> bool:
        from django.contrib.auth.hashers import check_password

        return check_password(raw_code, self.code_hash)

    @classmethod
    def issue(cls, member, request_ip=None):
        raw_code = _generate_otp_code()
        otp = cls.objects.create(
            member=member,
            code_hash=_hash_otp_code(raw_code),
            expires_at=timezone.now() + timedelta(seconds=cls.TTL_SECONDS),
            request_ip=request_ip,
        )
        # Invalidate any earlier still-live OTP for this member — only
        # the most recently issued code should ever be usable (spec:
        # "invalidate previous OTP when appropriate").
        cls.objects.filter(member=member, consumed=False).exclude(pk=otp.pk).update(consumed=True)
        return otp, raw_code


class RenewalAuthorization(models.Model):
    """The actual "you may renew this member" credential — issued once,
    only after RenewalOTP verification succeeds. /api/renew requires
    this token and resolves the member FROM it; it never trusts a
    client-supplied member_number/phone again at that point (spec
    section 6: destination/identity must be server-resolved, not
    re-trusted from the request body a second time)."""

    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="renewal_authorizations")
    token_hash = models.CharField(max_length=128, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    TTL_SECONDS = 600  # 10 minutes — enough to fill in payment method, not enough to be left lying around

    def is_valid(self):
        return self.used_at is None and timezone.now() < self.expires_at

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def issue(cls, member):
        import secrets as _secrets

        from django.contrib.auth.hashers import make_password

        raw_token = _secrets.token_urlsafe(32)
        auth = cls.objects.create(
            member=member,
            token_hash=make_password(raw_token),
            expires_at=timezone.now() + timedelta(seconds=cls.TTL_SECONDS),
        )
        return auth, raw_token

    @classmethod
    def resolve(cls, raw_token):
        """Look up the live authorization matching this raw token, or
        None. Tokens are hashed at rest (same reasoning as Payment's
        access token and RenewalOTP's code), so this has to check
        candidates rather than a direct lookup — the set of currently
        non-expired, unused authorizations is small in practice."""
        from django.contrib.auth.hashers import check_password

        candidates = cls.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now()).select_related("member")
        for candidate in candidates:
            if check_password(raw_token, candidate.token_hash):
                return candidate
        return None
