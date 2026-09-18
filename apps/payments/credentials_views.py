from django import forms
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action

from .crypto import mask_value
from .models import PaymentCredentials

SECRET_FIELDS = [
    "payhero_api_username", "payhero_api_password", "payhero_channel_id",
    "mpesa_consumer_key", "mpesa_consumer_secret", "mpesa_passkey", "mpesa_shortcode",
]


class CredentialsForm(forms.Form):
    payhero_api_username = forms.CharField(required=False, help_text="Leave blank to keep the current value.")
    payhero_api_password = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    payhero_channel_id = forms.CharField(
        required=False,
        help_text="NOT the same as your PayHero account ID. Find this under Payment Channels in your PayHero dashboard (app.payhero.co.ke) — it's the ID tied to your specific paybill/till/bank channel.",
    )
    payhero_callback_base_url = forms.CharField(
        required=False,
        help_text="e.g. https://egup.example.com/payments/callback/payhero/ — not secret, shown as entered.",
    )
    mpesa_environment = forms.ChoiceField(choices=[("sandbox", "Sandbox"), ("production", "Production")], required=False)
    mpesa_consumer_key = forms.CharField(required=False)
    mpesa_consumer_secret = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    mpesa_passkey = forms.CharField(required=False, widget=forms.PasswordInput(render_value=False))
    mpesa_shortcode = forms.CharField(required=False)


@require_permission("payments.credentials")
def credentials_edit(request):
    creds = PaymentCredentials.get_solo()
    key_configured = bool(getattr(settings, "FIELD_ENCRYPTION_KEY", ""))

    if not key_configured:
        # Fail visibly and helpfully, BEFORE touching the form/crypto layer
        # at all — not as an uncaught 500 mid-save. In production
        # (DEBUG=False) an uncaught exception here would show the visitor
        # a blank generic error page with no indication of what to fix;
        # this renders the actual instructions on the page instead.
        messages.error(
            request,
            "FIELD_ENCRYPTION_KEY is not set on this server, so credentials can't be saved here yet. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\" — set it as an environment variable, "
            "then restart the server and try again.",
        )
        current_values = {field: "(encryption not configured)" for field in SECRET_FIELDS}
        return render(request, "admin_dashboard/payment_credentials.html", {
            "form": CredentialsForm(), "current_values": current_values, "creds": creds,
            "key_configured": False,
        })

    if request.method == "POST":
        form = CredentialsForm(request.POST)
        if form.is_valid():
            changed_fields = []
            for field in SECRET_FIELDS:
                value = form.cleaned_data.get(field, "")
                if value:  # blank = "leave unchanged", never overwrite with blank
                    setattr(creds, field, value)
                    changed_fields.append(field)
            creds.payhero_callback_base_url = form.cleaned_data.get("payhero_callback_base_url") or creds.payhero_callback_base_url
            creds.mpesa_environment = form.cleaned_data.get("mpesa_environment") or creds.mpesa_environment
            creds.updated_by = request.user
            creds.save()
            # Audit WHICH fields changed, never the values themselves.
            log_action("payment_credentials.update", request=request, actor=request.user, obj=creds, fields_changed=changed_fields)
            messages.success(request, "Credentials saved. Only the fields you filled in were updated.")
            return redirect("payments_admin:credentials")
    else:
        form = CredentialsForm(initial={
            "payhero_callback_base_url": creds.payhero_callback_base_url,
            "mpesa_environment": creds.mpesa_environment,
        })

    current_values = {field: mask_value(getattr(creds, field)) for field in SECRET_FIELDS}
    return render(request, "admin_dashboard/payment_credentials.html", {
        "form": form, "current_values": current_values, "creds": creds, "key_configured": True,
    })


class PaymentSettingsForm(forms.Form):
    """Non-secret payment configuration (spec section 19) — separate from
    CredentialsForm above, which handles encrypted secrets. This form
    controls WHICH payment modes are offered and the manual payment
    instructions, none of which need encryption."""
    automatic_payment_enabled = forms.BooleanField(
        required=False,
        help_text="Only takes effect if PayHero credentials are actually configured — otherwise automatic stays hidden regardless of this toggle.",
    )
    manual_payment_enabled = forms.BooleanField(required=False, help_text="The fallback path — recommended to always keep this on.")
    manual_payment_paybill = forms.CharField(required=False, label="PayBill number")
    manual_payment_till = forms.CharField(required=False, label="Till number", help_text="Leave blank if using a PayBill instead.")
    manual_payment_account_note = forms.CharField(required=False, label="Account/reference instructions",
                                                   help_text="e.g. 'Use your application number as the account number.'")
    manual_payment_instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 4}))
    manual_payment_screenshot_required = forms.BooleanField(required=False, label="Require a payment screenshot")
    membership_fee_kes = forms.IntegerField(min_value=1, label="Registration fee (KES)")
    renewal_fee_kes = forms.IntegerField(min_value=1, label="Renewal fee (KES)")


@require_permission("payments.credentials")
def payment_settings_edit(request):
    from apps.members.models import SystemSettings

    settings_obj = SystemSettings.get_solo()
    if request.method == "POST":
        form = PaymentSettingsForm(request.POST)
        if form.is_valid():
            for field, value in form.cleaned_data.items():
                setattr(settings_obj, field, value)
            settings_obj.save()
            log_action("payment_settings.update", request=request, actor=request.user, obj=settings_obj)
            messages.success(request, "Payment settings saved.")
            return redirect("payments_admin:settings")
    else:
        form = PaymentSettingsForm(initial={
            "automatic_payment_enabled": settings_obj.automatic_payment_enabled,
            "manual_payment_enabled": settings_obj.manual_payment_enabled,
            "manual_payment_paybill": settings_obj.manual_payment_paybill,
            "manual_payment_till": settings_obj.manual_payment_till,
            "manual_payment_account_note": settings_obj.manual_payment_account_note,
            "manual_payment_instructions": settings_obj.manual_payment_instructions,
            "manual_payment_screenshot_required": settings_obj.manual_payment_screenshot_required,
            "membership_fee_kes": settings_obj.membership_fee_kes,
            "renewal_fee_kes": settings_obj.renewal_fee_kes,
        })

    from .providers import is_automatic_payment_available
    return render(request, "admin_dashboard/payment_settings.html", {
        "form": form, "automatic_actually_available": is_automatic_payment_available(),
    })
