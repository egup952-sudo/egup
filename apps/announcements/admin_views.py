from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action

from .models import Announcement


class AnnouncementForm(forms.ModelForm):
    class Meta:
        model = Announcement
        fields = ["title", "body", "status", "is_featured", "publish_at", "expire_at"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 6}),
            "publish_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expire_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


@require_permission("announcements.manage")
def list_announcements(request):
    announcements = Announcement.objects.all()
    return render(request, "admin_dashboard/announcements_list.html", {"announcements": announcements})


@require_permission("announcements.manage")
def create_announcement(request):
    form = AnnouncementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        log_action("announcement.create", request=request, actor=request.user, obj=obj)
        messages.success(request, "Announcement created.")
        return redirect("announcements_admin:list")
    return render(request, "admin_dashboard/announcement_form.html", {"form": form, "is_new": True})


@require_permission("announcements.manage")
def edit_announcement(request, pk):
    obj = get_object_or_404(Announcement, pk=pk)
    form = AnnouncementForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action("announcement.edit", request=request, actor=request.user, obj=obj)
        messages.success(request, "Announcement updated.")
        return redirect("announcements_admin:list")
    return render(request, "admin_dashboard/announcement_form.html", {"form": form, "is_new": False, "announcement": obj})


@require_permission("announcements.manage")
@require_POST
def delete_announcement(request, pk):
    obj = get_object_or_404(Announcement, pk=pk)
    log_action("announcement.delete", request=request, actor=request.user, obj=obj, title=obj.title)
    obj.delete()
    messages.success(request, "Announcement deleted.")
    return redirect("announcements_admin:list")
