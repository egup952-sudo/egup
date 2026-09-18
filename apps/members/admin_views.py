import csv
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action
from apps.memberships.models import Membership

from .models import Church, County, Department, Member, Profession, Skill, generate_membership_number


class AdminMemberForm(forms.ModelForm):
    """Admin-side member creation — bypasses payment entirely (the
    resulting Membership period is recorded with source=ADMIN_GRANT, an
    option that already existed on the Membership model but had no view
    using it). For walk-in registrations, corrections, or members who
    paid outside the online flow (cash at an event, etc.)."""

    skills = forms.ModelMultipleChoiceField(queryset=Skill.objects.filter(is_active=True), required=False, widget=forms.CheckboxSelectMultiple)
    departments = forms.ModelMultipleChoiceField(queryset=Department.objects.filter(is_active=True), required=False, widget=forms.CheckboxSelectMultiple)
    grant_membership_years = forms.IntegerField(initial=1, min_value=1, max_value=5, help_text="How many years of active membership to grant immediately.")

    class Meta:
        model = Member
        fields = [
            "surname", "other_names", "phone_number", "email", "gender", "county", "location",
            "home_town", "religion", "church", "profession", "experience", "gift",
            "referee_name", "referee_phone", "referee_location", "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["county"].queryset = County.objects.all()
        self.fields["church"].queryset = Church.objects.filter(is_active=True)
        self.fields["profession"].queryset = Profession.objects.filter(is_active=True)

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        qs = Member.objects.filter(email=email) if email else Member.objects.none()
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if email and qs.exists():
            raise forms.ValidationError("A member with this email already exists.")
        return email

    def clean_phone_number(self):
        phone = self.cleaned_data["phone_number"].strip()
        qs = Member.objects.filter(phone_number=phone)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("A member with this phone number already exists.")
        return phone


@require_permission("members.view")
def member_list(request):
    from django.db.models import Q

    query = request.GET.get("q", "").strip()
    members = Member.objects.select_related("county", "church").order_by("-created_at")
    if query:
        members = members.filter(
            Q(membership_number__icontains=query) | Q(phone_number__icontains=query)
            | Q(surname__icontains=query) | Q(other_names__icontains=query)
        )
    return render(request, "admin_dashboard/members_list.html", {"members": members[:200], "query": query})


@require_permission("members.edit")
def member_create(request):
    form = AdminMemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member = form.save(commit=False)
        member.membership_number = generate_membership_number()
        member.save()
        form.save_m2m()  # skills/departments

        years = form.cleaned_data["grant_membership_years"]
        today = timezone.now().date()
        Membership.objects.create(
            member=member,
            start_date=today,
            expiry_date=today + timedelta(days=365 * years),
            status="ACTIVE",
            source="ADMIN_GRANT",
            created_by_admin=request.user,
        )
        log_action("member.admin_create", request=request, actor=request.user, obj=member,
                   membership_number=member.membership_number, granted_years=years)
        messages.success(request, f"Member created — membership number {member.membership_number}.")
        return redirect("members_admin:detail", pk=member.pk)
    return render(request, "admin_dashboard/member_form.html", {"form": form})


@require_permission("members.view")
def member_detail(request, pk):
    member = get_object_or_404(Member.objects.select_related("county", "church", "profession"), pk=pk)
    memberships = member.memberships.order_by("-start_date")
    return render(request, "admin_dashboard/member_detail.html", {"member": member, "memberships": memberships})


@require_permission("members.export")
def member_export(request):
    from apps.audit.csv_utils import csv_safe

    log_action("members.export", request=request, actor=request.user)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="egup_members.csv"'
    writer = csv.writer(response)
    writer.writerow(["Membership Number", "Full Name", "Phone", "Email", "County", "Active", "Created"])
    for m in Member.objects.select_related("county").all():
        writer.writerow([csv_safe(m.membership_number), csv_safe(m.full_name), csv_safe(m.phone_number),
                          csv_safe(m.email), csv_safe(m.county.name if m.county else ""), m.is_active, m.created_at])
    return response
