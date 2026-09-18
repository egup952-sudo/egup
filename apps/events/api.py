"""Ticket booking for events with requires_ticket=True. Deliberately thin:
every actual payment mechanic (STK push, manual PayBill, verification,
rate limiting) is the SAME code apps.members.api already uses for
registration/renewal — this file only creates the EventTicket row and
calls into apps.payments.services, exactly the way apps.members.api does.
Settlement (marking a ticket CONFIRMED once its payment is PAID) lives in
apps.payments.services._confirm_event_ticket, not here — same reasoning
as membership settlement: one place decides "did this actually get
paid", not every caller.
"""
import functools
import json
import logging

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from apps.payments.models import Payment
from apps.payments.providers import is_automatic_payment_available, is_manual_payment_available
from apps.payments.rate_limit import check_payment_initiation_allowed
from apps.payments.services import initiate_manual_payment, initiate_payment

from .models import Event, EventTicket

logger = logging.getLogger(__name__)


def log_unhandled_errors(view_func):
    """Same wrapper as apps.members.api — see that file's docstring for
    why this exists (an unhandled exception must not surface as a
    content-less HTML 500 the frontend can't parse)."""

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
def ticket_modes(request, slug):
    """Same shape/purpose as apps.members.api.payment_modes, scoped to
    one event — the frontend needs this before it can even show the
    booking cards (price, capacity, which payment methods to offer)."""
    event = get_object_or_404(Event, slug=slug, status="PUBLISHED", requires_ticket=True)
    from apps.members.models import SystemSettings

    settings_obj = SystemSettings.get_solo()
    return JsonResponse({
        "price_kes": event.ticket_price_kes,
        "is_free": event.ticket_price_kes == 0,
        "capacity": event.ticket_capacity,
        "remaining": event.tickets_remaining,
        "is_sold_out": event.is_sold_out,
        "automatic_available": is_automatic_payment_available() if event.ticket_price_kes else False,
        "manual_available": is_manual_payment_available() if event.ticket_price_kes else False,
        "manual": {
            "paybill": settings_obj.manual_payment_paybill,
            "till": settings_obj.manual_payment_till,
            "account_note": settings_obj.manual_payment_account_note,
            "instructions": settings_obj.manual_payment_instructions,
            "screenshot_required": settings_obj.manual_payment_screenshot_required,
        },
    })


@csrf_protect
@require_POST
@log_unhandled_errors
def book_ticket(request, slug):
    event = get_object_or_404(Event, slug=slug, status="PUBLISHED", requires_ticket=True)
    body = _json_body(request)

    full_name = (body.get("full_name") or "").strip()
    email = (body.get("email") or "").strip()
    phone = (body.get("phone") or "").strip()
    try:
        quantity = max(1, int(body.get("quantity") or 1))
    except (TypeError, ValueError):
        quantity = 1
    quantity = min(quantity, 20)  # sanity cap — not a real capacity control, just rejects absurd input

    if not full_name or not phone:
        return JsonResponse({"error": "Name and phone number are required."}, status=400)

    allowed, retry_after = check_payment_initiation_allowed(phone)
    if not allowed:
        return JsonResponse(
            {"error": f"Too many attempts from this number. Try again in about {retry_after // 60 or 1} minute(s)."},
            status=429,
        )

    # Capacity check-and-create must be one atomic unit, not two separate
    # steps — otherwise two concurrent requests for the last ticket can
    # both read "1 remaining", both pass, and both create a ticket
    # (overselling). Locking the Event row serializes concurrent bookings
    # for the SAME event; select_for_update() requires an open
    # transaction, hence the explicit atomic() block.
    with transaction.atomic():
        event = Event.objects.select_for_update().get(pk=event.pk)
        if event.tickets_remaining is not None and quantity > event.tickets_remaining:
            return JsonResponse({
                "error": f"Only {event.tickets_remaining} ticket{'s' if event.tickets_remaining != 1 else ''} left for this event."
            }, status=409)

        ticket = EventTicket.objects.create(
            event=event, full_name=full_name, email=email, phone=phone, quantity=quantity,
        )

    # Free event: nothing to pay, confirm immediately — no Payment row
    # at all, matching "not every event needs a ticket booking [flow
    # with payment]" as literally as the paid path matches it fully.
    if event.ticket_price_kes == 0:
        ticket.status = "CONFIRMED"
        ticket.confirmed_at = timezone.now()
        ticket.save(update_fields=["status", "confirmed_at"])
        return JsonResponse({
            "ticket_reference": ticket.reference_code, "status": "CONFIRMED", "requires_payment": False,
        })

    amount = event.ticket_price_kes * quantity
    payment_method = (body.get("payment_method") or "").upper()

    if payment_method == "AUTOMATIC":
        if not is_automatic_payment_available():
            return JsonResponse({"error": "Automatic M-Pesa payment isn't available right now."}, status=503)
        payment = initiate_payment(
            purpose="EVENT_TICKET", amount_kes=amount, phone_number=phone,
            callback_base_url=settings.PAYHERO_CALLBACK_BASE_URL, request=request,
        )
    elif payment_method == "MANUAL":
        if not is_manual_payment_available():
            return JsonResponse({"error": "Manual payment isn't available right now."}, status=503)
        payment = initiate_manual_payment(
            purpose="EVENT_TICKET", amount_kes=amount, phone_number=phone, request=request,
        )
    else:
        return JsonResponse({"error": "Choose a payment method."}, status=400)

    ticket.payment = payment
    ticket.save(update_fields=["payment"])

    return JsonResponse({
        "ticket_reference": ticket.reference_code, "status": "PENDING_PAYMENT", "requires_payment": True,
        "payment_id": str(payment.id), "access_token": payment._raw_access_token,
        "payment_method": payment_method, "amount": amount,
    })
