from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action
from .models import Church, County, Department, Profession, Skill

# Registration reference data is content admins should be able to
# maintain without a deploy (new church added, a skill option retired,
# etc.) — brief section 13's "no hardcoded data admins can't change"
# spirit, applied to the registration wizard's dropdowns specifically.
MODEL_REGISTRY = {
    "counties": (County, "County"),
    "churches": (Church, "Church"),
    "skills": (Skill, "Skill"),
    "professions": (Profession, "Profession"),
    "departments": (Department, "Department"),
}


def _get_model(kind):
    entry = MODEL_REGISTRY.get(kind)
    if not entry:
        from django.http import Http404
        raise Http404("Unknown reference data type")
    return entry


class _SimpleForm(forms.ModelForm):
    class Meta:
        fields = "__all__"


@require_permission("content.view")
def reference_list(request, kind):
    model, label = _get_model(kind)
    items = model.objects.all()
    return render(request, "admin_dashboard/reference_list.html", {
        "items": items, "kind": kind, "label": label, "registry": MODEL_REGISTRY,
    })


@require_permission("content.create")
def reference_create(request, kind):
    model, label = _get_model(kind)
    form_class = forms.modelform_factory(model, form=_SimpleForm, fields="__all__")
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        log_action(f"reference_data.{kind}.create", request=request, actor=request.user, obj=obj)
        messages.success(request, f"{label} added.")
        return redirect("members_admin:reference_list", kind=kind)
    return render(request, "admin_dashboard/reference_form.html", {"form": form, "label": label, "kind": kind, "is_new": True})


@require_permission("content.edit")
def reference_edit(request, kind, pk):
    model, label = _get_model(kind)
    obj = get_object_or_404(model, pk=pk)
    form_class = forms.modelform_factory(model, form=_SimpleForm, fields="__all__")
    form = form_class(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action(f"reference_data.{kind}.edit", request=request, actor=request.user, obj=obj)
        messages.success(request, f"{label} updated.")
        return redirect("members_admin:reference_list", kind=kind)
    return render(request, "admin_dashboard/reference_form.html", {"form": form, "label": label, "kind": kind, "is_new": False, "obj": obj})


@require_permission("content.delete")
@require_POST
def reference_delete(request, kind, pk):
    model, label = _get_model(kind)
    obj = get_object_or_404(model, pk=pk)
    # Reference rows are PROTECTed or SET_NULL from Member/RegistrationIntent
    # (see apps.members.models) — deleting one that's in use by an existing
    # member will correctly raise/be prevented rather than silently
    # corrupting historical member records.
    try:
        obj.delete()
        log_action(f"reference_data.{kind}.delete", request=request, actor=request.user, metadata={"name": str(obj)})
        messages.success(request, f"{label} deleted.")
    except Exception:
        messages.error(request, f"Couldn't delete this {label.lower()} — it's still referenced by existing members. "
                                 f"Consider marking it inactive instead, if supported.")
    return redirect("members_admin:reference_list", kind=kind)
