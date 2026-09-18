"""
JSON API for the original frontend wizard (registration.html/renewal.html).
Endpoint paths and response shapes match the original
assets/js/worker-client.js contract exactly, so the wizard's own JS
(membership-registration.js, renewal.js) needed no logic changes — only
their import swapped from worker-client.js to django-client.js, which
calls these same paths.
"""
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from apps.audit.models import log_action
from apps.payments.models import ManualPaymentSubmission, Payment
from apps.payments.providers import is_automatic_payment_available, is_manual_payment_available
from apps.payments.rate_limit import (
    check_existing_active_payment, check_manual_submission_cooldown, check_payment_initiation_allowed,
)
from apps.payments.services import initiate_manual_payment, initiate_payment, submit_manual_payment

from .models import Church, County, Department, Member, Profession, RegistrationIntent, Skill, SystemSettings

logger = logging.getLogger(__name__)


def log_unhandled_errors(view_func):
    """Wraps a view so ANY unhandled exception is logged with its full
    traceback before returning a plain JSON 500 — instead of Django's
    default HTML error page, which the frontend's fetch wrapper can't
    parse as JSON and so falls back to a generic, unhelpful "Something
    went wrong" message with zero trace of what actually failed. This
    doesn't change any deliberate error handling already in the view
    (those still return their own specific messages) — it only catches
    what would otherwise be a silent, undiagnosable 500."""
    import functools

    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except Exception:
            logger.exception("Unhandled error in %s", view_func.__name__)
            return JsonResponse(
                {"error": "Something went wrong on our end. Please try again in a moment, or contact EGUP if it persists."},
                status=500,
            )

    return wrapper


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


@require_GET
def payment_modes(request):
    """Tells the wizard which payment options to actually show (spec
    section 3/24) — computed fresh on every call, never hardcoded on the
    frontend. If automatic is unavailable, the wizard should quietly show
    only manual, not an error."""
    settings_obj = SystemSettings.get_solo()
    return JsonResponse({
        "automatic_available": is_automatic_payment_available(),
        "manual_available": is_manual_payment_available(),
        # Both fees, not a single ambiguous "amount_kes" — this endpoint
        # is shared by registration.html AND renewal.html (renewal.js
        # calls it too), and the two fees are configured independently.
        "registration_fee_kes": settings_obj.membership_fee_kes,
        "renewal_fee_kes": settings_obj.renewal_fee_kes,
        "manual": {
            "paybill": settings_obj.manual_payment_paybill,
            "till": settings_obj.manual_payment_till,
            "account_note": settings_obj.manual_payment_account_note,
            "instructions": settings_obj.manual_payment_instructions,
            "screenshot_required": settings_obj.manual_payment_screenshot_required,
        },
    })


@require_GET
def reference_data(request):
    """Replaces reference-data.js's Supabase fetchTable calls."""
    return JsonResponse({
        "counties": [{"id": c.id, "name": c.name} for c in County.objects.all()],
        "churches": [{"id": c.id, "name": c.name} for c in Church.objects.filter(is_active=True)],
        "professions": [{"id": p.id, "name": p.name} for p in Profession.objects.filter(is_active=True)],
        "skills": [{"id": s.id, "name": s.name} for s in Skill.objects.filter(is_active=True)],
        "departments": [{"id": d.id, "name": d.name} for d in Department.objects.filter(is_active=True)],
    })


@csrf_protect
@require_POST
@log_unhandled_errors
def register(request):
    """Matches worker-client.js's registerMember(payload) — accepts the
    exact field names the wizard's state.data object uses."""
    body = _json_body(request)

    required = ["surname", "other_names", "phone", "gender", "county_id"]
    missing = [f for f in required if not body.get(f)]
    if missing:
        return JsonResponse({"error": "Missing required fields.", "fieldErrors": {f: "Required" for f in missing}}, status=400)

    phone = body["phone"].strip()
    email = (body.get("email") or "").strip()
    if email and Member.objects.filter(email=email).exists():
        return JsonResponse({"error": "This email is already registered.", "fieldErrors": {"email": "Already registered"}}, status=400)
    if Member.objects.filter(phone_number=phone).exists():
        return JsonResponse({"error": "This phone number is already registered.", "fieldErrors": {"phone": "Already registered"}}, status=400)

    try:
        county = County.objects.get(pk=body["county_id"])
    except (County.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"error": "Invalid county.", "fieldErrors": {"county_id": "Invalid"}}, status=400)

    intent = RegistrationIntent.objects.create(
        surname=body["surname"].strip(),
        other_names=body["other_names"].strip(),
        phone_number=phone,
        email=email,
        gender=body["gender"],
        county=county,
        location=body.get("location", ""),
        home_town=body.get("home_town", ""),
        religion=body.get("religion", ""),
        church_id=body.get("church_id") or None,
        profession_id=body.get("profession_id") or None,
        experience=body.get("experience", ""),
        gift=body.get("gift", ""),
        referee_name=body.get("referee_name", ""),
        referee_phone=body.get("referee_phone", ""),
        referee_location=body.get("referee_location", ""),
    )
    skill_ids = body.get("skill_ids") or []
    dept_ids = body.get("department_ids") or []
    if skill_ids:
        intent.skills.set(Skill.objects.filter(pk__in=skill_ids))
    if dept_ids:
        intent.departments.set(Department.objects.filter(pk__in=dept_ids))

    log_action("registration_intent.create", request=request, obj=intent)

    fee = SystemSettings.get_solo().membership_fee_kes
    payment_method = "MANUAL" if body.get("payment_method") == "MANUAL" else "AUTOMATIC"

    if payment_method == "AUTOMATIC" and not is_automatic_payment_available():
        # Frontend should already only offer this when available (see
        # /api/payment-modes), but the backend re-checks — never trust a
        # client-supplied "which mode" claim over what's actually configured.
        payment_method = "MANUAL" if is_manual_payment_available() else None
    if payment_method is None:
        return JsonResponse({"error": "No payment method is currently available. Please contact EGUP directly."}, status=503)

    # Spec section 8: one active payment per registration, plus a
    # phone-level rate limit. Both are enforced server-side, not just by
    # disabling a button — see apps.payments.rate_limit.
    existing = check_existing_active_payment(registration_intent=intent)
    if existing:
        # access_token_hash can't be reversed back into the original raw
        # token (it's hashed the same way a password would be) — so a
        # resumed payment needs a FRESH token issued now, not the one
        # from whenever it was first created. Without this, every retry
        # (reload the page, come back later, network hiccup) silently
        # handed the frontend a null token, and every subsequent manual
        # submission attempt would fail with a 403.
        raw_token = existing.issue_access_token()
        return JsonResponse({
            "member_id": intent.id, "payment_id": str(existing.id),
            "application_number": existing.application_number, "payment_method": existing.provider,
            "access_token": raw_token,
            "note": "resumed_existing_payment",
        })
    allowed, retry_after = check_payment_initiation_allowed(phone)
    if not allowed:
        return JsonResponse({"error": f"Too many payment attempts. Please wait about {retry_after} seconds and try again."}, status=429)

    try:
        if payment_method == "AUTOMATIC":
            payment = initiate_payment(
                purpose="REGISTRATION", amount_kes=fee, phone_number=phone,
                registration_intent=intent, callback_base_url=settings.PAYHERO_CALLBACK_BASE_URL,
                request=request,
            )
        else:
            payment = initiate_manual_payment(
                purpose="REGISTRATION", amount_kes=fee, phone_number=phone,
                registration_intent=intent, request=request,
            )
    except Exception:
        return JsonResponse({"error": "We couldn't start the payment request. Please try again shortly."}, status=502)

    return JsonResponse({
        "member_id": intent.id, "payment_id": str(payment.id),
        "application_number": payment.application_number, "payment_method": payment_method,
        "access_token": getattr(payment, "_raw_access_token", None),
    })


@require_GET
def payment_verify(request):
    """Matches worker-client.js's verifyPayment(paymentId) /
    pollPaymentStatus. Re-checks the real payment status server-side
    (services.py already guarantees this never trusts a callback blindly)
    rather than trusting anything the client sends.

    Requires the access token issued when this payment was created (spec
    section 6/7) — a payment UUID alone is not proof of ownership.
    Returns 403 (not 404) on a wrong/missing token so a caller can't use
    the response code itself to distinguish 'wrong token' from 'right
    payment, right token' by probing."""
    payment_id = request.GET.get("payment_id")
    token = request.GET.get("access_token", "")
    if not payment_id:
        return JsonResponse({"error": "Missing payment_id"}, status=400)
    try:
        payment = Payment.objects.select_related("member").get(pk=payment_id)
    except (Payment.DoesNotExist, ValueError):
        return JsonResponse({"error": "Payment not found"}, status=404)

    if not payment.verify_access_token(token):
        return JsonResponse({"error": "Not authorized to view this payment."}, status=403)

    data = {"status": payment.status, "application_number": payment.application_number}
    if payment.status == "PAID" and payment.member:
        membership = payment.member.memberships.order_by("-start_date").first()
        data["member_number"] = payment.member.membership_number
        if membership:
            data["expiry_date"] = membership.expiry_date.isoformat()
    return JsonResponse(data)


@csrf_protect
@require_POST
@log_unhandled_errors
def renewal_request_otp(request):
    """Step 1 of the secure renewal flow (spec section 3). Looks up the
    member by membership_number/phone (still the only way to identify
    WHICH account, same as before) but issues an OTP to their
    *registered* phone rather than letting that lookup alone unlock
    renewal. Response is intentionally identical whether or not a match
    was found — section 3.14: "do not reveal whether a membership
    exists through different responses"."""
    from .models import RenewalOTP
    from .sms import send_otp_sms

    body = _json_body(request)
    member_number = (body.get("member_number") or "").strip().upper()
    phone = (body.get("phone") or "").strip()
    client_ip = request.META.get("REMOTE_ADDR")

    generic_response = JsonResponse({
        "message": "If that membership exists, a verification code has been sent to the phone number on file."
    })

    if not member_number and not phone:
        return JsonResponse({"error": "Enter your membership number or phone number."}, status=400)

    # Rate limit on the LOOKUP VALUE itself (not just IP) — otherwise an
    # attacker enumerating membership numbers just rotates IPs, or an
    # attacker targeting one specific member's phone just rotates the
    # membership number guesses. Reuses the same cache-backed limiter as
    # payment attempts (now correctly shared across workers — see
    # settings.py CACHES).
    rate_key = f"renewal_otp:{member_number or phone}"
    allowed, retry_after = check_payment_initiation_allowed(rate_key)
    if not allowed:
        logger.warning("Renewal OTP rate limit hit for %s from %s", rate_key, client_ip)
        return generic_response  # same generic response even when throttled — don't leak that a limit exists here

    member = None
    if member_number:
        member = Member.objects.filter(membership_number=member_number, is_active=True).first()
    elif phone:
        member = Member.objects.filter(phone_number=phone, is_active=True).first()

    if member:
        otp, raw_code = RenewalOTP.issue(member, request_ip=client_ip)
        send_otp_sms(member.phone_number, raw_code)
        log_action("renewal.otp_requested", request=request, obj=member)
    else:
        # No matching member — do the same amount of "work" either way
        # so response timing doesn't itself reveal existence, then log
        # for suspicious-activity review (section 3.15) without
        # revealing anything to the caller.
        logger.info("Renewal OTP requested for non-existent member/phone from %s", client_ip)

    return generic_response


@csrf_protect
@require_POST
@log_unhandled_errors
def renewal_verify_otp(request):
    """Step 2: verify the code, issue a short-lived single-use
    RenewalAuthorization token. This token — not the membership number —
    is what /api/renew actually trusts from here on."""
    from .models import Member, RenewalAuthorization, RenewalOTP

    body = _json_body(request)
    member_number = (body.get("member_number") or "").strip().upper()
    phone = (body.get("phone") or "").strip()
    code = (body.get("code") or "").strip()

    if not code or (not member_number and not phone):
        return JsonResponse({"error": "Enter the code that was sent to you."}, status=400)

    member = None
    if member_number:
        member = Member.objects.filter(membership_number=member_number, is_active=True).first()
    elif phone:
        member = Member.objects.filter(phone_number=phone, is_active=True).first()

    generic_error = JsonResponse({"error": "That code is invalid or has expired."}, status=400)
    if not member:
        return generic_error

    otp = RenewalOTP.objects.filter(member=member, consumed=False).order_by("-created_at").first()
    if not otp or not otp.is_valid():
        return generic_error

    with transaction.atomic():
        # Lock the row before checking/incrementing attempts — two
        # concurrent verify calls with different guesses must not both
        # read attempts=4 and both get a 5th try.
        otp = RenewalOTP.objects.select_for_update().get(pk=otp.pk)
        if not otp.is_valid():
            return generic_error
        if not otp.check_code(code):
            otp.attempts += 1
            otp.save(update_fields=["attempts"])
            log_action("renewal.otp_failed", request=request, obj=member, attempts=otp.attempts)
            return generic_error

        otp.consumed = True
        otp.save(update_fields=["consumed"])

    auth, raw_token = RenewalAuthorization.issue(member)
    log_action("renewal.otp_verified", request=request, obj=member)
    return JsonResponse({"renewal_auth_token": raw_token, "expires_in": RenewalAuthorization.TTL_SECONDS})


@csrf_protect
@require_POST
@log_unhandled_errors
def renew(request):
    """Matches worker-client.js's renewMembership(payload) — this single
    call does BOTH the lookup AND starts the payment.

    SECURITY: the member is now resolved from a verified
    RenewalAuthorization token (proof of phone ownership via OTP — see
    renewal_request_otp/renewal_verify_otp above), never from a
    client-supplied member_number/phone at this step. Knowing or
    guessing a membership number used to be enough on its own to start a
    real payment/STK push against a stranger's phone; it no longer is."""
    from .models import RenewalAuthorization

    body = _json_body(request)
    raw_token = (body.get("renewal_auth_token") or "").strip()
    if not raw_token:
        return JsonResponse({"error": "Your renewal session has expired. Please verify your phone number again."}, status=401)

    with transaction.atomic():
        auth = RenewalAuthorization.resolve(raw_token)
        if not auth or not auth.is_valid():
            return JsonResponse({"error": "Your renewal session has expired. Please verify your phone number again."}, status=401)
        # Single-use, marked immediately (not after payment succeeds) —
        # spec section 3.10: "authorization cannot be reused". A failed
        # payment attempt requires a fresh OTP, a deliberate tradeoff for
        # a strict single-use guarantee rather than a race-prone "use it
        # only once we know payment succeeded".
        auth.mark_used()
        member = auth.member

    if not member.is_active:
        return JsonResponse({"error": "This membership is not currently active."}, status=404)

    fee = SystemSettings.get_solo().renewal_fee_kes
    payment_method = "MANUAL" if body.get("payment_method") == "MANUAL" else "AUTOMATIC"
    if payment_method == "AUTOMATIC" and not is_automatic_payment_available():
        payment_method = "MANUAL" if is_manual_payment_available() else None
    if payment_method is None:
        return JsonResponse({"error": "No payment method is currently available. Please contact EGUP directly."}, status=503)

    existing = check_existing_active_payment(member=member)
    if existing:
        # Same reasoning as the registration endpoint above: the raw
        # token from whenever this payment was first created can't be
        # recovered from its hash, so a resumed renewal needs a fresh one.
        raw_token = existing.issue_access_token()
        current_membership = member.memberships.order_by("-start_date").first()
        return JsonResponse({
            "payment_id": str(existing.id), "application_number": existing.application_number,
            "payment_method": existing.provider, "access_token": raw_token,
            "amount": existing.amount_kes, "note": "resumed_existing_payment",
            "member": {
                "name": member.full_name, "member_number": member.membership_number,
                "current_expiry": current_membership.expiry_date.isoformat() if current_membership else None,
            },
        })
    allowed, retry_after = check_payment_initiation_allowed(member.phone_number)
    if not allowed:
        return JsonResponse({"error": f"Too many payment attempts. Please wait about {retry_after} seconds and try again."}, status=429)

    try:
        if payment_method == "AUTOMATIC":
            payment = initiate_payment(
                purpose="RENEWAL", amount_kes=fee, phone_number=member.phone_number,
                member=member, callback_base_url=settings.PAYHERO_CALLBACK_BASE_URL, request=request,
            )
        else:
            payment = initiate_manual_payment(
                purpose="RENEWAL", amount_kes=fee, phone_number=member.phone_number,
                member=member, request=request,
            )
    except Exception:
        return JsonResponse({"error": "We couldn't start the payment request. Please try again shortly."}, status=502)

    current_membership = member.memberships.order_by("-start_date").first()
    return JsonResponse({
        "payment_id": str(payment.id),
        "application_number": payment.application_number,
        "payment_method": payment_method,
        "access_token": getattr(payment, "_raw_access_token", None),
        "amount": fee,
        "member": {
            "name": member.full_name,
            "member_number": member.membership_number,
            "current_expiry": current_membership.expiry_date.isoformat() if current_membership else None,
        },
    })


@csrf_protect
@require_POST
@log_unhandled_errors
def manual_payment_submit(request):
    """The manual-verification counterpart to /api/register and
    /api/renew — the applicant already has a Payment (created with
    provider=MANUAL by one of those endpoints) and is now submitting
    proof of their own M-Pesa payment. This NEVER marks anything PAID
    (see services.submit_manual_payment) — it only queues it for an
    admin to check against their own M-Pesa records."""
    from datetime import datetime

    from django.core.exceptions import ValidationError

    payment_id = request.POST.get("payment_id") or _json_body(request).get("payment_id")
    if not payment_id:
        return JsonResponse({"error": "Missing payment_id"}, status=400)
    try:
        payment = Payment.objects.get(pk=payment_id, provider="MANUAL")
    except (Payment.DoesNotExist, ValueError):
        return JsonResponse({"error": "Payment not found"}, status=404)

    token = request.POST.get("access_token") or _json_body(request).get("access_token", "")
    if not payment.verify_access_token(token):
        return JsonResponse({"error": "Not authorized to submit payment for this application."}, status=403)

    submission_count = payment.manual_submissions.count()
    from apps.payments.rate_limit import MAX_MANUAL_SUBMISSIONS_PER_PAYMENT, check_manual_submission_cooldown

    if submission_count >= MAX_MANUAL_SUBMISSIONS_PER_PAYMENT:
        return JsonResponse({"error": "Too many submission attempts for this application. Please contact EGUP directly."}, status=429)
    allowed, retry_after = check_manual_submission_cooldown(payment.id)
    if not allowed:
        return JsonResponse({"error": f"Please wait about {retry_after} seconds before submitting again."}, status=429)

    # BUG FIX: this used to be `is_multipart = bool(request.FILES)` — which
    # only checks whether a FILE was actually attached, not whether the
    # request itself is multipart-encoded. The screenshot is optional
    # (see the form), so the common case — no screenshot attached — sent
    # a real multipart/form-data request with zero files, which made this
    # check False, which then tried to json.loads() the raw multipart
    # body as JSON. That silently fails and falls back to an empty {},
    # meaning transaction_code/phone/amount/date were ALL blank for every
    # submission that didn't attach a screenshot — the majority of them,
    # since it's explicitly optional. This is almost certainly why
    # submissions were failing with a validation error while the earlier
    # Payment (created at registration) still showed up fine elsewhere.
    is_multipart = request.content_type.startswith("multipart/form-data")
    data = request.POST if is_multipart else _json_body(request)

    transaction_code = data.get("transaction_code", "")
    phone_number_used = data.get("phone_number_used", "")
    try:
        amount_submitted = int(data.get("amount_submitted", 0))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Invalid amount."}, status=400)
    payment_date_raw = data.get("payment_date", "")
    try:
        payment_date = datetime.strptime(payment_date_raw, "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"error": "Invalid payment date."}, status=400)

    settings_obj = SystemSettings.get_solo()
    screenshot = request.FILES.get("screenshot")
    if settings_obj.manual_payment_screenshot_required and not screenshot:
        return JsonResponse({"error": "A payment screenshot is required."}, status=400)

    if screenshot:
        # Spec section 12: "Do not trust accept='image/*' from HTML" —
        # this is the same real validator (Pillow decode, MIME check,
        # size/dimension caps) gallery/hero uploads already use. Before
        # this fix, a manual-payment screenshot only had its PRESENCE
        # checked, never its actual content — a real gap.
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.media_lib.validators import validate_image_upload

        try:
            validate_image_upload(screenshot)
        except DjangoValidationError as exc:
            return JsonResponse({"error": exc.message if hasattr(exc, "message") else str(exc)}, status=400)

    try:
        submission = submit_manual_payment(
            payment=payment, transaction_code=transaction_code, phone_number_used=phone_number_used,
            amount_submitted=amount_submitted, payment_date=payment_date, screenshot=screenshot,
            request=request,
        )
    except ValidationError as exc:
        return JsonResponse({"error": "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)}, status=400)
    except Exception:
        return JsonResponse({"error": "We couldn't submit that payment. Please check your details and try again."}, status=400)

    return JsonResponse({
        "status": "PENDING_VERIFICATION",
        "application_number": payment.application_number,
        "message": "Payment submitted. EGUP is reviewing your payment.",
    })
