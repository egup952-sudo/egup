"""Shared helpers for CSV exports (apps.members.admin_views.member_export,
apps.payments.admin_views.payment_export, and any future export) — kept in
one place rather than duplicated per export, per the project's own
"centralize security logic" convention.
"""

_DANGEROUS_LEADING_CHARS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Neutralizes CSV/formula injection (spec section 34): a free-text
    field an applicant typed themselves (full_name, email, church name —
    anything without a strict validation regex, unlike phone numbers or
    M-Pesa transaction codes) could start with '=', '+', '-' or '@' and
    be interpreted as a live formula by Excel/Sheets when an admin opens
    the export — e.g. a name like '=HYPERLINK(...)' or a DDE/cmd
    injection payload. Prefixing with a single quote makes spreadsheet
    software display the value as plain text instead of evaluating it,
    without changing what a human reading the CSV actually sees.
    Leaves None/numbers/booleans/dates alone — only strings can carry a
    formula, and str() is applied for CSV writing regardless."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_DANGEROUS_LEADING_CHARS):
        return "'" + text
    return text
