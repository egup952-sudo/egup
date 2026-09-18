from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action
from apps.media_lib.models import MediaAsset
from apps.media_lib.validators import validate_image_upload
from django.core.exceptions import ValidationError

from .models import HeroSlide, SiteSetting, SocialLink, ContactMessage


class HeroSlideForm(forms.ModelForm):
    upload_image = forms.ImageField(required=False, help_text="Upload a new image for this slide, or leave blank to keep the current one.")

    class Meta:
        model = HeroSlide
        fields = ["title", "subtitle", "cta_label", "cta_url", "secondary_cta_label", "secondary_cta_url", "is_active", "display_order"]


class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = ["contact_email", "contact_phone", "address", "privacy_policy_content", "terms_content"]
        widgets = {"privacy_policy_content": forms.Textarea(attrs={"rows": 10}), "terms_content": forms.Textarea(attrs={"rows": 10})}


class SocialLinkForm(forms.ModelForm):
    class Meta:
        model = SocialLink
        fields = ["platform", "url", "display_order", "is_active"]
        widgets = {"platform": forms.TextInput(attrs={"placeholder": "e.g. Facebook, Instagram, YouTube, WhatsApp"})}
        help_texts = {"platform": "The icon on the site is picked automatically from this name — Facebook, Instagram, X/Twitter, YouTube, TikTok, WhatsApp, LinkedIn and Telegram are recognised; anything else gets a generic link icon."}


@require_permission("content.view")
def hero_list(request):
    slides = HeroSlide.objects.select_related("image").all()
    return render(request, "admin_dashboard/hero_list.html", {"slides": slides})


@require_permission("content.create")
def hero_create(request):
    form = HeroSlideForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        image_file = form.cleaned_data.get("upload_image")
        if not image_file:
            messages.error(request, "An image is required for a new hero slide.")
        else:
            try:
                validate_image_upload(image_file)
            except ValidationError as exc:
                messages.error(request, str(exc))
                return render(request, "admin_dashboard/hero_form.html", {"form": form, "is_new": True})
            asset = MediaAsset.objects.create(file=image_file, category="HERO", uploaded_by=request.user)
            slide = form.save(commit=False)
            slide.image = asset
            slide.save()
            log_action("hero.create", request=request, actor=request.user, obj=slide)
            messages.success(request, "Hero slide created. Existing slides were not affected.")
            return redirect("content_admin:hero_list")
    return render(request, "admin_dashboard/hero_form.html", {"form": form, "is_new": True})


@require_permission("content.edit")
def hero_edit(request, pk):
    slide = get_object_or_404(HeroSlide, pk=pk)
    form = HeroSlideForm(request.POST or None, request.FILES or None, instance=slide)
    if request.method == "POST" and form.is_valid():
        image_file = form.cleaned_data.get("upload_image")
        slide = form.save(commit=False)
        if image_file:
            try:
                validate_image_upload(image_file)
            except ValidationError as exc:
                messages.error(request, str(exc))
                return render(request, "admin_dashboard/hero_form.html", {"form": form, "is_new": False, "slide": slide})
            # New MediaAsset row — the OLD image asset/file is left untouched
            # (brief section 17: uploading a new hero image must never
            # replace/delete an unrelated existing image).
            slide.image = MediaAsset.objects.create(file=image_file, category="HERO", uploaded_by=request.user)
        slide.save()
        log_action("hero.edit", request=request, actor=request.user, obj=slide)
        messages.success(request, "Hero slide updated.")
        return redirect("content_admin:hero_list")
    return render(request, "admin_dashboard/hero_form.html", {"form": form, "is_new": False, "slide": slide})


@require_permission("content.delete")
@require_POST
def hero_delete(request, pk):
    slide = get_object_or_404(HeroSlide, pk=pk)
    log_action("hero.delete", request=request, actor=request.user, obj=slide, title=slide.title)
    slide.delete()  # deletes only this HeroSlide row; its MediaAsset (and other slides) are untouched
    messages.success(request, "Hero slide deleted.")
    return redirect("content_admin:hero_list")


@require_permission("settings.manage")
def site_settings(request):
    obj = SiteSetting.get_solo()
    form = SiteSettingForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action("settings.edit", request=request, actor=request.user, obj=obj)
        messages.success(request, "Settings saved.")
        return redirect("content_admin:site_settings")
    return render(request, "admin_dashboard/site_settings.html", {"form": form})


@require_permission("content.view")
def social_link_list(request):
    links = SocialLink.objects.all()
    return render(request, "admin_dashboard/social_link_list.html", {"links": links})


@require_permission("content.create")
def social_link_create(request):
    form = SocialLinkForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        link = form.save()
        log_action("social_link.create", request=request, actor=request.user, obj=link)
        messages.success(request, "Social link added.")
        return redirect("content_admin:social_link_list")
    return render(request, "admin_dashboard/social_link_form.html", {"form": form, "is_new": True})


@require_permission("content.edit")
def social_link_edit(request, pk):
    link = get_object_or_404(SocialLink, pk=pk)
    form = SocialLinkForm(request.POST or None, instance=link)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action("social_link.edit", request=request, actor=request.user, obj=link)
        messages.success(request, "Social link updated.")
        return redirect("content_admin:social_link_list")
    return render(request, "admin_dashboard/social_link_form.html", {"form": form, "is_new": False, "link": link})


@require_permission("content.delete")
@require_POST
def social_link_delete(request, pk):
    link = get_object_or_404(SocialLink, pk=pk)
    log_action("social_link.delete", request=request, actor=request.user, obj=link, platform=link.platform)
    link.delete()
    messages.success(request, "Social link removed.")
    return redirect("content_admin:social_link_list")


@require_permission("content.view")
def message_list(request):
    """Inbox for public contact-form submissions (apps.content.api ->
    ContactMessage). Read-only list + a mark read/unread toggle — there's
    no edit/delete here by design, this is a record of what was sent in,
    not admin-authored content."""
    qs = ContactMessage.objects.order_by("-created_at")
    filter_kind = request.GET.get("filter", "all")
    if filter_kind == "unread":
        qs = qs.filter(is_read=False)
    unread_count = ContactMessage.objects.filter(is_read=False).count()
    return render(request, "admin_dashboard/message_list.html", {
        "messages_list": qs, "unread_count": unread_count, "filter_kind": filter_kind,
    })


@require_permission("content.edit")
@require_POST
def message_toggle_read(request, pk):
    msg = get_object_or_404(ContactMessage, pk=pk)
    msg.is_read = not msg.is_read
    msg.save(update_fields=["is_read"])
    log_action("message.toggle_read", request=request, actor=request.user, obj=msg, is_read=msg.is_read)
    next_url = request.POST.get("next") or "content_admin:message_list"
    return redirect(next_url)
