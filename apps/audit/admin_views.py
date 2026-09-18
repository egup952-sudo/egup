from django.core.paginator import Paginator
from django.shortcuts import render

from apps.accounts.permissions import require_permission

from .models import AuditLog


@require_permission("dashboard.view")
def audit_list(request):
    """Read-only — there's nothing to create/edit/delete here by design,
    an audit trail that could be edited wouldn't be one."""
    qs = AuditLog.objects.select_related("actor").order_by("-created_at")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(action__icontains=q)
    paginator = Paginator(qs, 40)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "admin_dashboard/audit_list.html", {"page": page, "q": q})
