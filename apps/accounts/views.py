from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.announcements.models import Announcement
from apps.audit.models import AuditLog, log_action
from apps.events.models import Event
from apps.members.models import Member, RegistrationIntent
from apps.memberships.models import Membership
from apps.monitoring.rate_limit import get_client_ip, is_ip_blocked, record_attempt
from apps.payments.models import Payment

from .models import AdminProfile
from .permissions import require_permission


def dashboard_login(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard_home")

    error = None
    if request.method == "POST":
        ip = get_client_ip(request)
        blocked, mins = is_ip_blocked(ip)
        if blocked:
            error = f"Too many failed attempts. Try again in {mins or 'a few'} minutes."
        else:
            username = request.POST.get("username", "")
            password = request.POST.get("password", "")
            user = authenticate(request, username=username, password=password)
            if user is not None and hasattr(user, "admin_profile") and user.admin_profile.is_active:
                record_attempt(request, username, success=True)
                auth_login(request, user)
                log_action("login", request=request, actor=user)
                return redirect("accounts:dashboard_home")
            record_attempt(request, username, success=False, reason="invalid credentials or no admin profile")
            log_action("failed_login", request=request, metadata={"username_tried": username})
            error = "Invalid credentials."
    return render(request, "admin_dashboard/login.html", {"error": error})


@login_required(login_url="accounts:dashboard_login")
def dashboard_logout(request):
    log_action("logout", request=request, actor=request.user)
    auth_logout(request)
    return redirect("accounts:dashboard_login")


@require_permission("dashboard.view")
def dashboard_home(request):
    """Every number here comes from a live query — no hardcoded stats
    (brief section 13)."""
    from datetime import timedelta

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    from apps.content.models import ContactMessage

    now = timezone.now()
    today = now.date()
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = this_month_start - timedelta(seconds=1)
    last_month_start = last_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def pct_change(current, previous):
        """None when there's nothing to compare against (previous
        period had zero) — the template shows that as flat, not a
        misleading +/-infinite%."""
        if not previous:
            return None
        return round(((current - previous) / previous) * 100, 1)

    stats = {
        "total_members": Member.objects.count(),
        "active_memberships": Membership.objects.filter(status="ACTIVE").count(),
        "expired_memberships": Membership.objects.filter(status="EXPIRED").count(),
        "pending_registrations": RegistrationIntent.objects.filter(status="PENDING_PAYMENT").count(),
        "payments_pending": Payment.objects.filter(status__in=["PENDING", "PROCESSING"]).count(),
        "payments_paid": Payment.objects.filter(status="PAID").count(),
        "payments_failed": Payment.objects.filter(status__in=["FAILED", "CANCELLED", "EXPIRED"]).count(),
        "revenue_kes": sum(Payment.objects.filter(status="PAID").values_list("amount_kes", flat=True)),
        "published_events": Event.objects.filter(status="PUBLISHED").count(),
        "published_announcements": Announcement.objects.filter(status="PUBLISHED").count(),
        "unread_messages": ContactMessage.objects.filter(is_read=False).count(),
    }

    # ---- Month-over-month deltas for the stat cards (real aggregates,
    # not the running totals above — a % change needs two comparable
    # periods, e.g. members *joined* this month vs last month).
    members_this_month = Member.objects.filter(created_at__gte=this_month_start).count()
    members_last_month = Member.objects.filter(created_at__gte=last_month_start, created_at__lt=this_month_start).count()
    active_this_month = Membership.objects.filter(status="ACTIVE", start_date__gte=this_month_start.date()).count()
    active_last_month = Membership.objects.filter(status="ACTIVE", start_date__gte=last_month_start.date(), start_date__lt=this_month_start.date()).count()
    revenue_this_month = sum(Payment.objects.filter(status="PAID", settled_at__gte=this_month_start).values_list("amount_kes", flat=True))
    revenue_last_month = sum(Payment.objects.filter(status="PAID", settled_at__gte=last_month_start, settled_at__lt=this_month_start).values_list("amount_kes", flat=True))
    pending_this_month = Payment.objects.filter(status__in=["PENDING", "PROCESSING"], created_at__gte=this_month_start).count()
    pending_last_month = Payment.objects.filter(status__in=["PENDING", "PROCESSING"], created_at__gte=last_month_start, created_at__lt=this_month_start).count()

    stat_trends = {
        "total_members": pct_change(members_this_month, members_last_month),
        "active_memberships": pct_change(active_this_month, active_last_month),
        "revenue_kes": pct_change(revenue_this_month, revenue_last_month),
        "payments_pending": pct_change(pending_this_month, pending_last_month),
    }

    recent_payments = Payment.objects.select_related("member", "registration_intent").order_by("-created_at")[:6]
    recent_audit = AuditLog.objects.select_related("actor").order_by("-created_at")[:15]

    upcoming_events = Event.objects.filter(status="PUBLISHED", starts_at__gte=now).order_by("starts_at")[:3]

    # ---- "Needs Attention" (spec section 25): the dashboard should
    # surface issues automatically, not make an admin go looking for them.
    from apps.payments.models import ManualPaymentSubmission

    pending_manual = ManualPaymentSubmission.objects.filter(verification_status="PENDING")
    needs_attention = {
        "pending_verification_count": pending_manual.count(),
        "low_confidence_count": pending_manual.filter(confidence="LOW").count(),
        "suspicious_count": Payment.objects.filter(status="SUSPICIOUS").count(),
        "verified_automatic_count": Payment.objects.filter(status="PAID", provider="PAYHERO").count(),
        "verified_manual_count": Payment.objects.filter(status="PAID", provider="MANUAL").count(),
    }
    notification_count = needs_attention["pending_verification_count"] + needs_attention["suspicious_count"]

    # ---- Chart data: everything below is a real aggregate query, not a
    # placeholder. Last 6 months, oldest first, so the chart reads left-to-right.
    six_months_ago = (timezone.now().replace(day=1) - timedelta(days=150))
    revenue_by_month = (
        Payment.objects.filter(status="PAID", settled_at__gte=six_months_ago)
        .annotate(month=TruncMonth("settled_at"))
        .values("month").annotate(total=Sum("amount_kes")).order_by("month")
    )
    members_by_month = (
        Member.objects.filter(created_at__gte=six_months_ago)
        .annotate(month=TruncMonth("created_at"))
        .values("month").annotate(count=Count("id")).order_by("month")
    )
    active_by_month = (
        Membership.objects.filter(status="ACTIVE", start_date__gte=six_months_ago.date())
        .annotate(month=TruncMonth("start_date"))
        .values("month").annotate(count=Count("id")).order_by("month")
    )
    pending_by_month = (
        Payment.objects.filter(status__in=["PENDING", "PROCESSING"], created_at__gte=six_months_ago)
        .annotate(month=TruncMonth("created_at"))
        .values("month").annotate(count=Count("id")).order_by("month")
    )
    payment_status_breakdown = (
        Payment.objects.values("status").annotate(count=Count("id")).order_by("status")
    )

    chart_data = {
        "revenue_labels": [r["month"].strftime("%b %Y") for r in revenue_by_month],
        "revenue_values": [r["total"] for r in revenue_by_month],
        "members_labels": [m["month"].strftime("%b %Y") for m in members_by_month],
        "members_values": [m["count"] for m in members_by_month],
        "active_values": [a["count"] for a in active_by_month],
        "pending_values": [p["count"] for p in pending_by_month],
        "status_labels": [dict(Payment.STATUS_CHOICES).get(s["status"], s["status"]) for s in payment_status_breakdown],
        "status_values": [s["count"] for s in payment_status_breakdown],
    }

    # ---- Membership distribution donut: bucket each MEMBER once, by
    # their most recent Membership row, so the four slices sum to
    # total_members exactly (no double-counting a member who has both
    # an old expired row and a current active one).
    soon_cutoff = today + timedelta(days=30)
    latest_membership_by_member = {}
    for m in Membership.objects.order_by("member_id", "-start_date").only("member_id", "status", "expiry_date"):
        latest_membership_by_member.setdefault(m.member_id, m)

    distribution = {"active": 0, "expiring_soon": 0, "expired": 0, "cancelled": 0}
    for member_id in Member.objects.values_list("id", flat=True):
        ms = latest_membership_by_member.get(member_id)
        if ms is None or ms.status == "EXPIRED" or (ms.status == "ACTIVE" and ms.expiry_date < today):
            distribution["expired"] += 1
        elif ms.status == "CANCELLED":
            distribution["cancelled"] += 1
        elif ms.status == "ACTIVE" and ms.expiry_date <= soon_cutoff:
            distribution["expiring_soon"] += 1
        else:
            distribution["active"] += 1
    dist_total = stats["total_members"] or 1
    membership_distribution = {
        "total": stats["total_members"],
        "active": distribution["active"],
        "active_pct": round(distribution["active"] / dist_total * 100, 1),
        "expiring_soon": distribution["expiring_soon"],
        "expiring_soon_pct": round(distribution["expiring_soon"] / dist_total * 100, 1),
        "expired": distribution["expired"],
        "expired_pct": round(distribution["expired"] / dist_total * 100, 1),
        "cancelled": distribution["cancelled"],
        "cancelled_pct": round(distribution["cancelled"] / dist_total * 100, 1),
    }

    # ---- Registration funnel: each stage is a real count from a
    # different model/state, not a guess — see each field's own query.
    funnel_registered = RegistrationIntent.objects.count()
    funnel_payment_initiated = Payment.objects.filter(purpose="REGISTRATION").count()
    funnel_payment_completed = Payment.objects.filter(purpose="REGISTRATION", status="PAID").count()
    funnel_activated = Member.objects.count()
    funnel_base = funnel_registered or 1
    registration_funnel = [
        {"label": "Registered", "count": funnel_registered, "pct": 100.0},
        {"label": "Payment Initiated", "count": funnel_payment_initiated, "pct": round(funnel_payment_initiated / funnel_base * 100, 1)},
        {"label": "Payment Completed", "count": funnel_payment_completed, "pct": round(funnel_payment_completed / funnel_base * 100, 1)},
        {"label": "Membership Activated", "count": funnel_activated, "pct": round(funnel_activated / funnel_base * 100, 1)},
    ]

    return render(request, "admin_dashboard/home.html", {
        "stats": stats, "stat_trends": stat_trends, "recent_payments": recent_payments, "recent_audit": recent_audit,
        "chart_data": chart_data, "needs_attention": needs_attention, "notification_count": notification_count,
        "upcoming_events": upcoming_events, "membership_distribution": membership_distribution,
        "registration_funnel": registration_funnel,
    })
