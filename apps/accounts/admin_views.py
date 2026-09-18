from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit.models import log_action

from .models import AdminProfile, Role
from .permissions import require_permission

User = get_user_model()


class NewAdminForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput, min_length=10,
                                help_text="At least 10 characters. The admin should change this after first login.")
    role = forms.ModelChoiceField(queryset=Role.objects.all())

    def clean_username(self):
        username = self.cleaned_data["username"]
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("A user with this username already exists.")
        return username


class EditAdminForm(forms.ModelForm):
    class Meta:
        model = AdminProfile
        fields = ["role", "is_active"]


@require_permission("admins.manage")
def admin_list(request):
    profiles = AdminProfile.objects.select_related("user", "role").order_by("-created_at")
    return render(request, "admin_dashboard/admins_list.html", {"profiles": profiles})


@require_permission("admins.manage")
def admin_create(request):
    form = NewAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.create(
            username=form.cleaned_data["username"],
            email=form.cleaned_data["email"],
            password=make_password(form.cleaned_data["password"]),
            is_staff=False,  # deliberately NOT django-admin staff — see AdminProfile docstring
        )
        profile = AdminProfile.objects.create(user=user, role=form.cleaned_data["role"])
        log_action("admin_user.create", request=request, actor=request.user, obj=profile,
                   new_admin_username=user.username, role=profile.role.name)
        messages.success(request, f"Admin account created for {user.username}. Share the password with them securely and ask them to change it.")
        return redirect("accounts:admin_list")
    return render(request, "admin_dashboard/admin_form.html", {"form": form, "is_new": True})


@require_permission("admins.manage")
def admin_edit(request, pk):
    profile = get_object_or_404(AdminProfile, pk=pk)
    form = EditAdminForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action("admin_user.edit", request=request, actor=request.user, obj=profile,
                   role=profile.role.name, is_active=profile.is_active)
        messages.success(request, "Admin account updated.")
        return redirect("accounts:admin_list")
    return render(request, "admin_dashboard/admin_form.html", {"form": form, "is_new": False, "profile": profile})


@require_permission("admins.manage")
@require_POST
def admin_deactivate(request, pk):
    """Revokes dashboard access immediately without deleting the account
    or its audit trail (AdminProfile.is_active, not a delete)."""
    profile = get_object_or_404(AdminProfile, pk=pk)
    if profile.user_id == request.user.id:
        messages.error(request, "You can't deactivate your own account.")
        return redirect("accounts:admin_list")
    profile.is_active = False
    profile.save(update_fields=["is_active"])
    log_action("admin_user.deactivate", request=request, actor=request.user, obj=profile)
    messages.success(request, "Admin account deactivated.")
    return redirect("accounts:admin_list")
