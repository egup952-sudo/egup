from django.urls import path
from . import admin_views

app_name = "announcements_admin"

urlpatterns = [
    path("", admin_views.list_announcements, name="list"),
    path("new/", admin_views.create_announcement, name="create"),
    path("<int:pk>/edit/", admin_views.edit_announcement, name="edit"),
    path("<int:pk>/delete/", admin_views.delete_announcement, name="delete"),
]
