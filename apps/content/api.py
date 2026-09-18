import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from apps.audit.models import log_action

from .models import ContactMessage


@csrf_protect
@require_POST
def contact_submit(request):
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        body = request.POST

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    message = (body.get("message") or "").strip()
    if not name or not email or not message:
        return JsonResponse({"error": "Please fill in your name, email and message."}, status=400)

    msg = ContactMessage.objects.create(
        name=name, email=email, phone=(body.get("phone") or "").strip(),
        subject=(body.get("subject") or "").strip(), message=message,
    )
    log_action("contact_message.create", request=request, obj=msg)
    return JsonResponse({"received": True})
