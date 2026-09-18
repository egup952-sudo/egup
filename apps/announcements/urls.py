from django.urls import path
from . import views

app_name = "announcements"

urlpatterns = [
    path("announcements.html", views.list_announcements, name="list"),
]
