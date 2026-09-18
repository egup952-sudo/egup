from django.urls import path
from . import views, api

app_name = "events"

urlpatterns = [
    path("events.html", views.list_events, name="list"),
    path("events/<slug:slug>.html", views.detail, name="detail"),

    path("api/events/<slug:slug>/ticket-modes", api.ticket_modes, name="api_ticket_modes"),
    path("api/events/<slug:slug>/book-ticket", api.book_ticket, name="api_book_ticket"),
]
