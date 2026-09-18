from django.urls import path

from . import api, views

app_name = "members"

urlpatterns = [
    path("registration.html", views.register, name="register"),
    path("renewal.html", views.renew, name="renew"),

    # JSON API — matches the original worker-client.js contract exactly.
    path("api/register", api.register, name="api_register"),
    path("api/payment/verify", api.payment_verify, name="api_payment_verify"),
    path("api/payment/manual-submit", api.manual_payment_submit, name="api_manual_payment_submit"),
    path("api/payment-modes", api.payment_modes, name="api_payment_modes"),
    path("api/renew", api.renew, name="api_renew"),
    path("api/renewal/request-otp", api.renewal_request_otp, name="api_renewal_request_otp"),
    path("api/renewal/verify-otp", api.renewal_verify_otp, name="api_renewal_verify_otp"),
    path("api/reference-data", api.reference_data, name="api_reference_data"),
]
