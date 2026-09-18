"""
Intelligent validation for manual M-Pesa payment submissions (spec
section 9). Kept separate from services.py so the "is this plausible"
checks are easy to test/extend on their own.
"""
import re

from django.core.exceptions import ValidationError

# Real Safaricom M-Pesa transaction codes are 10 characters, uppercase
# letters and digits (e.g. QJI7XXXXXX). We validate the SHAPE, not
# against Safaricom directly (there is no public API for that) — the
# actual truth-check is the admin's manual comparison against their own
# M-Pesa statement, which is the whole point of "pending verification."
TRANSACTION_CODE_RE = re.compile(r"^[A-Z0-9]{8,12}$")


def normalize_transaction_code(raw: str) -> str:
    """Uppercase, strip whitespace/spaces — 'qji 7xx xxx' and 'QJI7XXXXXX'
    should be treated as the same code."""
    return re.sub(r"\s+", "", (raw or "")).upper()


def validate_transaction_code(raw: str) -> str:
    code = normalize_transaction_code(raw)
    if not code:
        raise ValidationError("Transaction code is required.")
    if not TRANSACTION_CODE_RE.match(code):
        raise ValidationError("That doesn't look like a valid M-Pesa transaction code.")
    return code


def check_duplicate_transaction_code(code: str) -> bool:
    """True if this code has already been submitted by anyone, for any
    payment. The real, unbypassable guarantee is the DB unique
    constraint on ManualPaymentSubmission.transaction_code — this is a
    friendly pre-check so the applicant gets a clear message instead of
    a raw database error."""
    from .models import ManualPaymentSubmission

    return ManualPaymentSubmission.objects.filter(transaction_code=code).exists()


def compute_confidence(*, payment, transaction_code, phone_number_used, amount_submitted) -> tuple:
    """Rule-based reconciliation confidence (spec section 11). Returns
    (confidence, notes) — this RECOMMENDS a confidence level for the
    admin to see; it never auto-approves anything by itself."""
    notes = []
    confidence = "HIGH"

    if check_duplicate_transaction_code(transaction_code):
        return "LOW", "Transaction code has already been submitted elsewhere — flagged as suspicious."

    if amount_submitted != payment.amount_kes:
        confidence = "LOW"
        notes.append(f"Amount mismatch: expected KES {payment.amount_kes}, submitted KES {amount_submitted}.")

    on_file_phone = (payment.phone_number or "").strip()
    submitted_phone = (phone_number_used or "").strip()
    if on_file_phone and submitted_phone and on_file_phone != submitted_phone:
        if confidence != "LOW":
            confidence = "MEDIUM"
        notes.append(f"Phone number used ({submitted_phone}) differs from the number on the application ({on_file_phone}).")

    if not notes:
        notes.append("Application, amount, and transaction code all check out — recommended for verification.")

    return confidence, " ".join(notes)
