import json

from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Payment
from .services import handle_callback


@csrf_exempt  # external provider POST — CSRF tokens don't apply; protected by callback_token instead
@require_POST
def payhero_callback(request):
    token = request.GET.get("token")
    if not token:
        return HttpResponseForbidden("missing callback token")

    # Payment.DoesNotExist -> 403, not 404: don't reveal whether a token
    # format is merely wrong vs a real-but-expired one.
    if not Payment.objects.filter(callback_token=token).exists():
        return HttpResponseForbidden("invalid callback token")

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        body = {}

    payment = handle_callback(callback_token=token, body=body, request=request)
    # Always 200 to the provider regardless of our internal status, so it
    # doesn't retry-storm us for e.g. an amount-mismatch we've already
    # recorded as FAILED.
    return JsonResponse({"received": True, "payment_status": payment.status})
