from django import forms
from django.contrib import messages
from django.forms import inlineformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action

from .models import Page, PageBlock


class PageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = ["title", "slug", "status", "seo_title", "seo_description"]
        help_texts = {"slug": "Becomes the page's URL: /pages/<slug>.html"}


PageBlockFormSet = inlineformset_factory(
    Page, PageBlock,
    fields=["block_type", "content", "image", "order"],
    extra=1, can_delete=True,
    widgets={"content": forms.Textarea(attrs={"rows": 3})},
)


@require_permission("content.view")
def page_list(request):
    pages = Page.objects.all()
    return render(request, "admin_dashboard/pages_list.html", {"pages": pages})


@require_permission("content.create")
def page_create(request):
    form = PageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        page = form.save()
        log_action("page.create", request=request, actor=request.user, obj=page)
        messages.success(request, "Page created. Add content blocks below, then publish when ready.")
        return redirect("content_admin:page_edit", pk=page.pk)
    return render(request, "admin_dashboard/page_form.html", {"form": form, "is_new": True})


@require_permission("content.edit")
def page_edit(request, pk):
    page = get_object_or_404(Page, pk=pk)
    form = PageForm(request.POST or None, instance=page)
    formset = PageBlockFormSet(request.POST or None, request.FILES or None, instance=page)
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        form.save()
        formset.save()
        log_action("page.edit", request=request, actor=request.user, obj=page)
        messages.success(request, "Page saved.")
        return redirect("content_admin:page_edit", pk=page.pk)
    return render(request, "admin_dashboard/page_form.html", {
        "form": form, "formset": formset, "is_new": False, "page": page,
    })


@require_permission("content.publish")
@require_POST
def page_toggle_publish(request, pk):
    page = get_object_or_404(Page, pk=pk)
    from django.utils import timezone

    if page.status == "PUBLISHED":
        page.status = "DRAFT"
    else:
        page.status = "PUBLISHED"
        if not page.published_at:
            page.published_at = timezone.now()
    page.save(update_fields=["status", "published_at"])
    log_action("page.publish_toggle", request=request, actor=request.user, obj=page, status=page.status)
    messages.success(request, f"Page is now {page.get_status_display()}.")
    return redirect("content_admin:page_list")


@require_permission("content.delete")
@require_POST
def page_delete(request, pk):
    page = get_object_or_404(Page, pk=pk)
    log_action("page.delete", request=request, actor=request.user, obj=page, title=page.title)
    page.delete()
    messages.success(request, "Page deleted.")
    return redirect("content_admin:page_list")
