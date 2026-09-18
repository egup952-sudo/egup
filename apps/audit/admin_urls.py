from django.urls import path

from . import admin_views

app_name = "audit_admin"

urlpatterns = [
    path("", admin_views.audit_list, name="list"),
]
