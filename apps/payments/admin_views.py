from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action

from .models import ManualPaymentSubmission, Payment
from .services import _reverify_and_settle, flag_manual_payment_suspicious, reject_manual_payment, verify_manual_payment


@require_permission("payments.view")
def payment_list(request):
    status = request.GET.get("status", "")
    provider = request.GET.get("provider", "")
    query = request.GET.get("q", "").strip()

    payments = Payment.objects.select_related("member").order_by("-created_at")
    if status:
        payments = payments.filter(status=status)
    if provider:
        payments = payments.filter(provider=provider)
    if query:
        payments = payments.filter(
            models.Q(application_number__icontains=query)
            | models.Q(phone_number__icontains=query)
            | models.Q(manual_submission__transaction_code__icontains=query)
        ).distinct()

    return render(request, "admin_dashboard/payments_list.html", {
        "payments": payments[:200], "status": status, "provider": provider, "query": query,
        "status_choices": Payment.STATUS_CHOICES, "provider_choices": Payment.PROVIDER_CHOICES,
    })


@require_permission("payments.export")
def payment_export(request):
    """CSV export (spec section 26) — daily/weekly/monthly collections
    can be filtered/pivoted from this by whoever opens it in Excel;
    keeping this as one complete export rather than building separate
    daily/weekly/monthly report screens the project doesn't have time
    to get right before launch."""
    import csv

    from django.http import HttpResponse

    from apps.audit.csv_utils import csv_safe

    log_action("payments.export", request=request, actor=request.user)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="egup_payments.csv"'
    writer = csv.writer(response)
    writer.writerow(["Application Number", "Purpose", "Provider", "Amount KES", "Status", "Phone",
                      "Transaction Code", "M-Pesa Receipt", "Created", "Settled"])
    from .services import get_latest_manual_submission

    for p in Payment.objects.prefetch_related("manual_submissions").all():
        latest = get_latest_manual_submission(p)
        code = latest.transaction_code if latest else ""
        writer.writerow([csv_safe(p.application_number), p.get_purpose_display(), p.get_provider_display(),
                          p.amount_kes, p.get_status_display(), csv_safe(p.phone_number), csv_safe(code),
                          csv_safe(p.mpesa_receipt), p.created_at, p.settled_at or ""])
    return response


@require_permission("payments.view")
def payment_detail(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("member", "registration_intent"), pk=pk)
    attempts = payment.attempts.order_by("-created_at")
    manual_submissions = payment.manual_submissions.order_by("-submitted_at")
    return render(request, "admin_dashboard/payment_detail.html", {
        "payment": payment, "attempts": attempts, "manual_submissions": manual_submissions,
        "latest_manual_submission": manual_submissions.first(),
    })


@require_permission("payments.reconcile")
@require_POST
def payment_reconcile(request, pk):
    """Manually triggers the SAME independent-verification path the
    callback uses (services._reverify_and_settle) — an admin click can
    only ever ask 'please re-check with PayHero right now', never
    directly set status=PAID. This preserves the brief's 'never trust a
    click/callback blindly' rule even for admin-initiated reconciliation."""
    payment = get_object_or_404(Payment, pk=pk)
    if payment.status not in ("PROCESSING", "PENDING"):
        messages.info(request, f"Payment is already {payment.get_status_display()} — nothing to reconcile.")
        return redirect("payments_admin:detail", pk=pk)
    try:
        _reverify_and_settle(payment, request=request)
    except Exception as exc:
        messages.error(request, f"Reconciliation check failed: {exc}")
        return redirect("payments_admin:detail", pk=pk)
    log_action("payment.manual_reconcile", request=request, actor=request.user, obj=payment)
    messages.success(request, "Reconciliation check completed.")
    return redirect("payments_admin:detail", pk=pk)


@require_permission("payments.view")
def manual_verification_queue(request):
    """The 'Needs Attention' manual-verification screen (spec sections
    13/25). Pending items first, most confident matches first within
    that — the admin's time should go to genuinely ambiguous cases."""
    confidence_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    pending = list(
        ManualPaymentSubmission.objects.filter(verification_status="PENDING")
        .select_related("payment", "payment__member", "payment__registration_intent")
    )
    pending.sort(key=lambda s: confidence_order.get(s.confidence, 1))

    resolved = (
        ManualPaymentSubmission.objects.exclude(verification_status="PENDING")
        .select_related("payment").order_by("-verified_at")[:30]
    )

    summary = {
        "pending_count": len(pending),
        "high_confidence": sum(1 for s in pending if s.confidence == "HIGH"),
        "low_confidence": sum(1 for s in pending if s.confidence == "LOW"),
        "duplicate_flagged": Payment.objects.filter(status="SUSPICIOUS").count(),
    }
    return render(request, "admin_dashboard/manual_verification_queue.html", {
        "pending": pending, "resolved": resolved, "summary": summary,
    })


@require_permission("payments.reconcile")
@require_POST
def manual_verification_verify(request, pk):
    submission = get_object_or_404(ManualPaymentSubmission, pk=pk)
    notes = request.POST.get("notes", "")
    try:
        verify_manual_payment(submission=submission, admin_user=request.user, notes=notes, request=request)
        messages.success(request, f"Payment verified — {submission.payment.application_number} marked PAID.")
    except Exception as exc:
        messages.error(request, f"Couldn't verify this payment: {exc}")
    return redirect("payments_admin:manual_verification_queue")


@require_permission("payments.reconcile")
@require_POST
def manual_verification_reject(request, pk):
    submission = get_object_or_404(ManualPaymentSubmission, pk=pk)
    notes = request.POST.get("notes", "")
    if not notes.strip():
        messages.error(request, "Please add a note explaining the rejection — the applicant will need to know why.")
        return redirect("payments_admin:manual_verification_queue")
    reject_manual_payment(submission=submission, admin_user=request.user, notes=notes, request=request)
    messages.success(request, "Payment rejected.")
    return redirect("payments_admin:manual_verification_queue")


@require_permission("payments.reconcile")
@require_POST
def manual_verification_flag(request, pk):
    submission = get_object_or_404(ManualPaymentSubmission, pk=pk)
    notes = request.POST.get("notes", "")
    flag_manual_payment_suspicious(submission=submission, admin_user=request.user, notes=notes, request=request)
    messages.warning(request, "Payment flagged as suspicious.")
    return redirect("payments_admin:manual_verification_queue")


@require_permission("payments.view")
def manual_screenshot_view(request, pk):
    """Payment screenshots are evidence, not public content (spec section
    12: 'should not be freely publicly accessible... only authorized
    EGUP administrators should access payment evidence'). Serves the
    file through Django with an RBAC check instead of linking directly
    to the public /media/ URL, which has no authorization at all.

    For a high-traffic production deployment, swap this for
    X-Accel-Redirect (nginx) or a signed S3 URL rather than streaming
    through Django — documented as a known scaling limitation, not
    pretended to be solved here.
    """
    from django.http import FileResponse, Http404

    submission = get_object_or_404(ManualPaymentSubmission, pk=pk)
    if not submission.screenshot:
        raise Http404("No screenshot on file for this submission.")
    log_action("payment.screenshot_view", request=request, actor=request.user, obj=submission.payment)
    return FileResponse(submission.screenshot.open("rb"), filename=submission.screenshot.name.split("/")[-1])
