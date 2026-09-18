"""
The only place allowed to change a Payment's status or create a Member/
Membership as a result of payment. Every other view/endpoint calls into
here rather than touching Payment.status directly.

Ports two specific fixes from Project B's SECURITY-AUDIT-REPORT.md:

1. The callback is never trusted for status (see providers.py). This
   module's `handle_callback()` only uses the callback to find which
   Payment to re-check, then calls the provider's authenticated
   verify_transaction_status().

2. The race condition: two concurrent callbacks for the same payment could
   both read status=PROCESSING, both decide "not yet settled", and both
   proceed to settle -> duplicate membership. The audited fix was an
   atomic conditional UPDATE (`WHERE status = 'PROCESSING'`) so only one
   of the two writes can win. Django's ORM equivalent is
   `queryset.filter(status='PROCESSING').update(status='PAID', ...)` and
   checking the returned row count — that's exactly what
   `_atomically_mark_paid()` below does, inside select_for_update() for a
   second layer of protection against the same row.
"""
from django.db import transaction
from django.utils import timezone

from apps.audit.models import log_action
from apps.members.models import Member, RegistrationIntent, generate_membership_number
from apps.memberships.models import Membership

from .models import Payment, PaymentAttempt
from .providers import get_provider

VALID_TRANSITIONS = {
    "PENDING": {"PROCESSING", "PENDING_VERIFICATION", "CANCELLED", "EXPIRED"},
    "PROCESSING": {"PAID", "FAILED", "CANCELLED", "EXPIRED"},
    "PENDING_VERIFICATION": {"PAID", "REJECTED", "SUSPICIOUS"},
    "PAID": set(),        # terminal — no transition out, ever
    "FAILED": {"PROCESSING"},   # allow a fresh retry attempt
    "REJECTED": {"PENDING_VERIFICATION"},  # applicant can resubmit after a rejection
    "SUSPICIOUS": {"PAID", "REJECTED"},    # admin resolves a flagged submission either way
    "CANCELLED": set(),
    "EXPIRED": set(),
}


class InvalidTransition(Exception):
    pass


def transition_status(payment: Payment, new_status: str):
    if new_status not in VALID_TRANSITIONS.get(payment.status, set()):
        raise InvalidTransition(f"{payment.status} -> {new_status} is not allowed")
    payment.status = new_status
    payment.save(update_fields=["status", "updated_at"])


def initiate_payment(*, purpose, amount_kes, phone_number, registration_intent=None, member=None,
                      provider_name="PAYHERO", callback_base_url, request=None) -> Payment:
    payment = Payment.objects.create(
        purpose=purpose,
        provider=provider_name,
        amount_kes=amount_kes,
        phone_number=phone_number,
        registration_intent=registration_intent,
        member=member,
    )
    # Issued once, here, at creation — see Payment.issue_access_token's
    # docstring. Stashed as a transient (non-persisted) attribute so the
    # calling API view can hand it to the client that just created this
    # payment; it is never retrievable again after this response.
    payment._raw_access_token = payment.issue_access_token()
    provider = get_provider(provider_name)
    callback_url = f"{callback_base_url}?token={payment.callback_token}"
    try:
        result = provider.initiate_stk_push(
            amount=amount_kes,
            phone_number=phone_number,
            reference=str(payment.id),
            callback_url=callback_url,
        )
    except Exception as exc:
        PaymentAttempt.objects.create(
            payment=payment, kind="STK_PUSH", succeeded=False,
            response_payload={"error": str(exc)},
        )
        transition_status(payment, "FAILED")
        payment.failure_reason = str(exc)[:255]
        payment.save(update_fields=["failure_reason"])
        raise

    payment.provider_reference = result.provider_reference or ""
    payment.checkout_request_id = result.checkout_request_id or ""
    payment.save(update_fields=["provider_reference", "checkout_request_id"])
    transition_status(payment, "PROCESSING")
    PaymentAttempt.objects.create(payment=payment, kind="STK_PUSH", succeeded=True, response_payload=result.raw)
    log_action("payment.initiate", request=request, obj=payment, provider=provider_name, amount=amount_kes)
    return payment


def initiate_manual_payment(*, purpose, amount_kes, phone_number, registration_intent=None, member=None,
                             request=None) -> Payment:
    """Creates the Payment record for the manual M-Pesa path — no STK
    push, no external call. The applicant pays via PayBill/Till on their
    own, then submits a transaction code (submit_manual_payment). Stays
    in PENDING until they do, mirroring the "Mode B" flow in the spec:
    application created first, payment instructions shown, THEN the
    applicant acts."""
    payment = Payment.objects.create(
        purpose=purpose,
        provider="MANUAL",
        amount_kes=amount_kes,
        phone_number=phone_number,
        registration_intent=registration_intent,
        member=member,
    )
    payment._raw_access_token = payment.issue_access_token()
    log_action("payment.initiate_manual", request=request, obj=payment, amount=amount_kes)
    return payment


def get_latest_manual_submission(payment: Payment):
    """The current/most-recent manual submission attempt for a payment —
    payment.manual_submission (singular) no longer exists now that the
    field is a ForeignKey (multiple attempts per payment, so a rejected
    applicant can resubmit — see ManualPaymentSubmission's docstring).
    Every place that used to read payment.manual_submission should call
    this instead."""
    return payment.manual_submissions.order_by("-submitted_at").first()


def submit_manual_payment(*, payment: Payment, transaction_code: str, phone_number_used: str,
                           amount_submitted: int, payment_date, screenshot=None, request=None):
    """The applicant's half of manual verification (spec section 8-9).
    NEVER marks the payment PAID — only ever moves it to
    PENDING_VERIFICATION for an admin to review. Raises ValidationError
    (via validators.py) for a malformed/duplicate code before anything
    is written, and relies on the DB unique constraint on
    ManualPaymentSubmission.transaction_code as the real, race-proof
    guarantee against reuse (the pre-check in validators.py is just a
    friendlier error message for the common case)."""
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError

    from .models import ManualPaymentSubmission
    from .validators import compute_confidence, validate_transaction_code

    if payment.status not in ("PENDING", "REJECTED"):
        raise InvalidTransition(f"Cannot submit a manual payment for a payment in status {payment.status}")

    code = validate_transaction_code(transaction_code)
    confidence, notes = compute_confidence(
        payment=payment, transaction_code=code,
        phone_number_used=phone_number_used, amount_submitted=amount_submitted,
    )

    try:
        with transaction.atomic():
            submission = ManualPaymentSubmission.objects.create(
                payment=payment, transaction_code=code, phone_number_used=phone_number_used,
                amount_submitted=amount_submitted, payment_date=payment_date, screenshot=screenshot,
                confidence=confidence, confidence_notes=notes,
            )
            transition_status(payment, "PENDING_VERIFICATION")
    except IntegrityError:
        # The DB unique constraint caught a race the pre-check missed
        # (two submissions of the same code landing at nearly the same
        # moment) — same user-facing message either way.
        raise ValidationError("This M-Pesa transaction code has already been submitted.")

    log_action("payment.manual_submit", request=request, obj=payment,
               transaction_code=code, confidence=confidence)
    return submission


@transaction.atomic
def verify_manual_payment(*, submission, admin_user, notes="", request=None) -> Payment:
    """Admin action: confirms a manual submission against their own
    M-Pesa records and marks it PAID. This is the ONLY function allowed
    to move a manual payment to PAID — deliberately separate from
    submit_manual_payment so "user typed a code" and "admin confirmed
    it's real" can never be the same step (spec section 27's critical
    business rule).

    Wrapped in transaction.atomic(): select_for_update() below requires
    an open transaction on Postgres or it raises TransactionManagementError
    outright (this was missing before — every verification attempt was
    failing). The atomic block also makes the compare-and-swap below a
    real guarantee: two admins clicking "Verify" on the same submission
    at the same moment can't both succeed.
    """
    with transaction.atomic():
        locked = Payment.objects.select_for_update().filter(pk=submission.payment_id, status__in=("PENDING_VERIFICATION", "SUSPICIOUS"))
        updated_count = locked.update(status="PAID", settled_at=timezone.now())
        if updated_count == 0:
            payment = Payment.objects.get(pk=submission.payment_id)
            raise InvalidTransition(f"Cannot verify a payment in status {payment.status}")

        payment = Payment.objects.select_related("member", "registration_intent").get(pk=submission.payment_id)

        submission.verification_status = "VERIFIED"
        submission.verified_by = admin_user
        submission.verified_at = timezone.now()
        submission.verification_notes = notes
        submission.save(update_fields=["verification_status", "verified_by", "verified_at", "verification_notes"])

        if payment.purpose == "EVENT_TICKET":
            # Same branch as _atomically_mark_paid (the automatic-payment
            # settlement path) — this was missing here entirely, meaning
            # every manually-verified ticket payment silently created a
            # bogus Membership instead of confirming the actual ticket,
            # which was then stuck at PENDING_PAYMENT forever even though
            # its Payment showed PAID.
            _confirm_event_ticket(payment)
        else:
            _create_member_and_membership(payment, request=request)

        log_action("payment.manual_verify", request=request, actor=admin_user, obj=payment,
                   transaction_code=submission.transaction_code)
    return payment


def reject_manual_payment(*, submission, admin_user, notes="", request=None) -> Payment:
    with transaction.atomic():
        locked = Payment.objects.select_for_update().filter(pk=submission.payment_id, status__in=("PENDING_VERIFICATION", "SUSPICIOUS"))
        updated_count = locked.update(status="REJECTED", updated_at=timezone.now())
        if updated_count == 0:
            payment = Payment.objects.get(pk=submission.payment_id)
            raise InvalidTransition(f"Cannot reject a payment in status {payment.status}")
        payment = Payment.objects.get(pk=submission.payment_id)
        submission.verification_status = "REJECTED"
        submission.verified_by = admin_user
        submission.verified_at = timezone.now()
        submission.verification_notes = notes
        submission.save(update_fields=["verification_status", "verified_by", "verified_at", "verification_notes"])
        log_action("payment.manual_reject", request=request, actor=admin_user, obj=payment, notes=notes)
    return payment


def flag_manual_payment_suspicious(*, submission, admin_user, notes="", request=None) -> Payment:
    with transaction.atomic():
        locked = Payment.objects.select_for_update().filter(pk=submission.payment_id, status__in=("PENDING_VERIFICATION",))
        updated_count = locked.update(status="SUSPICIOUS", updated_at=timezone.now())
        if updated_count == 0:
            payment = Payment.objects.get(pk=submission.payment_id)
            raise InvalidTransition(f"Cannot flag a payment in status {payment.status}")
        payment = Payment.objects.get(pk=submission.payment_id)
        submission.verification_status = "SUSPICIOUS"
        submission.verified_by = admin_user
        submission.verified_at = timezone.now()
        submission.verification_notes = notes
        submission.save(update_fields=["verification_status", "verified_by", "verified_at", "verification_notes"])
        log_action("payment.manual_flag_suspicious", request=request, actor=admin_user, obj=payment, notes=notes)
    return payment


def handle_callback(*, callback_token: str, body: dict, request=None) -> Payment:
    """Entry point for the PayHero callback view. The token check happens
    in the view (before this is even called, per providers.py's note on
    our own bearer-token-in-URL scheme). This function still re-derives
    the payment from the token defensively, and NEVER reads a status out
    of `body` to decide anything."""
    payment = Payment.objects.select_related("member", "registration_intent").get(callback_token=callback_token)
    PaymentAttempt.objects.create(payment=payment, kind="CALLBACK", request_payload=body, succeeded=True)

    if payment.status in ("PAID", "CANCELLED", "EXPIRED"):
        # Already terminal — duplicate/late callback, safely ignored.
        return payment

    return _reverify_and_settle(payment, request=request)


def _reverify_and_settle(payment: Payment, request=None) -> Payment:
    provider = get_provider(payment.provider)
    result = provider.verify_transaction_status(payment.provider_reference)
    PaymentAttempt.objects.create(
        payment=payment, kind="STATUS_CHECK", succeeded=True,
        response_payload=result.raw,
    )

    if result.status == "PAID":
        # Defense in depth: confirm the provider's reported amount matches
        # what we initiated for, when the provider supplies one. Brief
        # section 8 requires verifying expected amount, not just status.
        if result.amount is not None and int(result.amount) != payment.amount_kes:
            transition_status(payment, "FAILED")
            payment.failure_reason = f"Amount mismatch: expected {payment.amount_kes}, provider reported {result.amount}"
            payment.save(update_fields=["failure_reason"])
            log_action("payment.amount_mismatch", request=request, obj=payment,
                       expected=payment.amount_kes, reported=result.amount)
            return payment
        return _atomically_mark_paid(payment, result.mpesa_receipt, request=request)

    if result.status in ("FAILED", "CANCELLED", "EXPIRED"):
        transition_status(payment, result.status)
        log_action(f"payment.{result.status.lower()}", request=request, obj=payment)

    return payment


def _atomically_mark_paid(payment: Payment, mpesa_receipt: str, request=None) -> Payment:
    """The compare-and-swap fix, ported from the audited Worker code.

    `.filter(status='PROCESSING').update(...)` only succeeds against a row
    that is STILL PROCESSING at the moment of the write — Postgres/Django
    evaluate the WHERE clause and UPDATE as one statement, so if two
    concurrent callers race, exactly one UPDATE affects a row and the
    other affects zero rows. select_for_update() adds a row lock as a
    second layer so the whole read-then-decide block for the winner is
    also serialized against any third concurrent caller.
    """
    with transaction.atomic():
        locked = Payment.objects.select_for_update().filter(pk=payment.pk, status="PROCESSING")
        updated_count = locked.update(status="PAID", mpesa_receipt=mpesa_receipt or "", settled_at=timezone.now())

        if updated_count == 0:
            # Someone else already settled this payment. Not an error —
            # return the current state, do NOT create a second membership.
            payment.refresh_from_db()
            return payment

        payment.refresh_from_db()
        if payment.purpose == "EVENT_TICKET":
            # A ticket purchase settling is not a membership event —
            # branch BEFORE _create_member_and_membership, which assumes
            # every non-REGISTRATION payment is a RENEWAL against
            # payment.member (see that function). Keeping this check
            # here, not inside that function, means the membership
            # settlement path — the security-audited compare-and-swap
            # logic this whole block exists for — is untouched either way.
            _confirm_event_ticket(payment)
        else:
            _create_member_and_membership(payment, request=request)
        log_action("payment.settle", request=request, obj=payment, mpesa_receipt=mpesa_receipt)

    return payment


def _confirm_event_ticket(payment: Payment):
    """Counterpart to _create_member_and_membership for purpose=EVENT_TICKET
    — runs inside the same atomic settlement block, so a ticket can't end
    up CONFIRMED without its payment being PAID, or vice versa.
    payment.event_ticket is a reverse FK manager (one Payment is only
    ever linked from the one EventTicket that created it, but the field
    isn't a OneToOne at the DB level), hence .first() not a direct attr."""
    ticket = payment.event_ticket.first()
    if ticket is None:
        return
    ticket.status = "CONFIRMED"
    ticket.confirmed_at = timezone.now()
    ticket.save(update_fields=["status", "confirmed_at"])


def _create_member_and_membership(payment: Payment, request=None):
    """Runs inside the same atomic block as the settlement UPDATE above,
    so a failure here rolls back the PAID status too — no half-created
    membership can exist without its payment being marked settled, and
    vice versa (brief section 11)."""
    from datetime import timedelta

    if payment.purpose == "REGISTRATION":
        intent: RegistrationIntent = payment.registration_intent
        member = Member.objects.create(
            membership_number=generate_membership_number(),
            surname=intent.surname,
            other_names=intent.other_names,
            phone_number=intent.phone_number,
            email=intent.email,
            gender=intent.gender,
            county=intent.county,
            location=intent.location,
            home_town=intent.home_town,
            religion=intent.religion,
            church=intent.church,
            profession=intent.profession,
            experience=intent.experience,
            gift=intent.gift,
            referee_name=intent.referee_name,
            referee_phone=intent.referee_phone,
            referee_location=intent.referee_location,
            registration_intent=intent,
        )
        member.skills.set(intent.skills.all())
        member.departments.set(intent.departments.all())
        intent.status = "SETTLED"
        intent.save(update_fields=["status"])
        payment.member = member
        payment.save(update_fields=["member"])
        source = "REGISTRATION"
    else:
        member = payment.member
        source = "RENEWAL"

    today = timezone.now().date()
    Membership.objects.create(
        member=member,
        payment=payment,
        start_date=today,
        expiry_date=today + timedelta(days=365),
        status="ACTIVE",
        source=source,
    )
