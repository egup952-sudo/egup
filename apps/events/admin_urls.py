from django.urls import path
from . import admin_views

app_name = "events_admin"

urlpatterns = [
    path("", admin_views.list_events, name="list"),
    path("new/", admin_views.create_event, name="create"),
    path("<int:pk>/edit/", admin_views.edit_event, name="edit"),
    path("<int:pk>/delete/", admin_views.delete_event, name="delete"),
    path("<int:pk>/tickets/", admin_views.ticket_list, name="ticket_list"),
]
