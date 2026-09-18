from django.db.models import Q
from django.shortcuts import render

from apps.accounts.permissions import require_permission


@require_permission("dashboard.view")
def admin_search(request):
    """Real site-wide search — replaces the disabled, decorative topbar
    search input that was there before. RBAC-aware: only searches
    categories the logged-in admin actually has permission to view, so
    a VIEWER-role admin doesn't see payment details they can't otherwise
    reach just by searching for them.
    """
    query = request.GET.get("q", "").strip()
    profile = getattr(request.user, "admin_profile", None)

    results = {"members": [], "payments": [], "events": [], "announcements": []}
    if not query or profile is None:
        return render(request, "admin_dashboard/search_results.html", {"query": query, "results": results})

    if profile.has_permission("members.view"):
        from apps.members.models import Member

        results["members"] = list(
            Member.objects.filter(
                Q(membership_number__icontains=query) | Q(phone_number__icontains=query)
                | Q(surname__icontains=query) | Q(other_names__icontains=query)
                | Q(email__icontains=query)
            ).select_related("county")[:20]
        )

    if profile.has_permission("payments.view"):
        from apps.payments.models import Payment

        results["payments"] = list(
            Payment.objects.filter(
                Q(application_number__icontains=query) | Q(phone_number__icontains=query)
                | Q(manual_submissions__transaction_code__icontains=query)
            ).select_related("member").distinct()[:20]
        )

    if profile.has_permission("content.view"):
        from apps.announcements.models import Announcement
        from apps.events.models import Event

        results["events"] = list(Event.objects.filter(title__icontains=query)[:20])
        results["announcements"] = list(Announcement.objects.filter(title__icontains=query)[:20])

    return render(request, "admin_dashboard/search_results.html", {"query": query, "results": results})
