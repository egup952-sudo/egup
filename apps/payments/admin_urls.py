from django.urls import path
from . import admin_views, credentials_views

app_name = "payments_admin"

urlpatterns = [
    path("", admin_views.payment_list, name="list"),
    path("export/", admin_views.payment_export, name="export"),
    path("manual-verification/", admin_views.manual_verification_queue, name="manual_verification_queue"),
    path("manual-verification/<int:pk>/verify/", admin_views.manual_verification_verify, name="manual_verification_verify"),
    path("manual-verification/<int:pk>/reject/", admin_views.manual_verification_reject, name="manual_verification_reject"),
    path("manual-verification/<int:pk>/flag/", admin_views.manual_verification_flag, name="manual_verification_flag"),
    path("manual-verification/<int:pk>/screenshot/", admin_views.manual_screenshot_view, name="manual_screenshot"),
    path("credentials/", credentials_views.credentials_edit, name="credentials"),
    path("settings/", credentials_views.payment_settings_edit, name="settings"),
    path("<uuid:pk>/", admin_views.payment_detail, name="detail"),
    path("<uuid:pk>/reconcile/", admin_views.payment_reconcile, name="reconcile"),
]
