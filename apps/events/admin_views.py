from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action
from apps.media_lib.models import MediaAsset
from apps.media_lib.validators import validate_image_upload

from .models import Event, EventTicket


class EventForm(forms.ModelForm):
    upload_image = forms.ImageField(
        required=False,
        help_text="Upload an image for this event directly (JPEG/PNG/WebP/GIF, up to 8MB). Leave blank to keep the current image, or clear it below to remove it.",
    )

    class Meta:
        model = Event
        fields = [
            "title", "description", "location", "starts_at", "ends_at", "registration_url", "status", "is_featured",
            "requires_ticket", "ticket_price_kes", "ticket_capacity",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 5}),
        }


def _save_event_image(form, event):
    """Uploading a new image for an event creates a NEW MediaAsset row
    (never overwrites/reuses another event's or the gallery's asset) —
    same pattern as hero slides, per the image-overwrite-bug fix."""
    image_file = form.cleaned_data.get("upload_image")
    if not image_file:
        return None
    try:
        validate_image_upload(image_file)
    except ValidationError:
        raise
    return MediaAsset.objects.create(file=image_file, category="EVENT", caption=event.title if event else "")


@require_permission("events.manage")
def list_events(request):
    events = Event.objects.all()
    return render(request, "admin_dashboard/events_list.html", {"events": events})


@require_permission("events.manage")
def create_event(request):
    form = EventForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        try:
            asset = _save_event_image(form, event)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, "admin_dashboard/event_form.html", {"form": form, "is_new": True})
        if asset:
            event.image = asset
        event.save()
        log_action("event.create", request=request, actor=request.user, obj=event)
        messages.success(request, "Event created.")
        return redirect("events_admin:list")
    return render(request, "admin_dashboard/event_form.html", {"form": form, "is_new": True})


@require_permission("events.manage")
def edit_event(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = EventForm(request.POST or None, request.FILES or None, instance=event)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        try:
            asset = _save_event_image(form, event)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, "admin_dashboard/event_form.html", {"form": form, "is_new": False, "event": event})
        if asset:
            # New asset for the new upload — the OLD image asset is left
            # untouched (not deleted), same as hero slides.
            event.image = asset
        event.save()
        log_action("event.edit", request=request, actor=request.user, obj=event)
        messages.success(request, "Event updated.")
        return redirect("events_admin:list")
    return render(request, "admin_dashboard/event_form.html", {"form": form, "is_new": False, "event": event})


@require_permission("events.manage")
@require_POST
def delete_event(request, pk):
    event = get_object_or_404(Event, pk=pk)
    log_action("event.delete", request=request, actor=request.user, obj=event, title=event.title)
    event.delete()
    messages.success(request, "Event deleted.")
    return redirect("events_admin:list")


@require_permission("events.manage")
def ticket_list(request, pk):
    """Read-only — a booking is created and confirmed by the public
    booking flow / payment settlement, not edited here. Cancelling a
    confirmed ticket (e.g. a refund) is deliberately not built yet;
    this view is for visibility, not ticket-desk operations."""
    event = get_object_or_404(Event, pk=pk)
    tickets = event.tickets.select_related("payment").order_by("-created_at")
    return render(request, "admin_dashboard/event_ticket_list.html", {"event": event, "tickets": tickets})
