from django.urls import path

from . import views

app_name = "payments"

urlpatterns = [
    path("callback/payhero/", views.payhero_callback, name="payhero_callback"),
]
