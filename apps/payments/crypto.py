"""
Symmetric encryption for credentials stored in the database (PayHero/
Daraja API secrets set via the admin dashboard). Per the brief: "Secrets
MUST NOT be stored as plaintext database configuration." Environment
variables remain the primary/fallback source (see providers.py); this
lets an admin set or rotate credentials from the dashboard without
shell/server access, while keeping the DB copy encrypted rather than
plaintext.

FIELD_ENCRYPTION_KEY must be a real Fernet key (32 url-safe base64 bytes).
Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Store it as an environment variable, exactly like SECRET_KEY — never in
source control. Losing this key makes any already-encrypted DB
credentials unrecoverable (they'd need to be re-entered) — that's the
correct failure mode for a real secret, not a bug.
"""
from django.conf import settings


def _get_fernet():
    from cryptography.fernet import Fernet

    key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
    if not key:
        raise RuntimeError(
            "FIELD_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
            "and set it as an environment variable before saving credentials via the dashboard."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        # Wrong/rotated key, corrupted value, or plaintext leftover from
        # before encryption was added — fail closed (empty), never raise
        # into a payment flow, and never fall back to treating it as
        # plaintext (that would defeat the point of encrypting it).
        return ""


def mask_value(plaintext: str) -> str:
    """For display only — never send the real secret back to a browser
    after it's been saved. Shows just enough to confirm which credential
    is configured without exposing it."""
    if not plaintext:
        return "(not set)"
    if len(plaintext) <= 4:
        return "••••"
    return f"{'•' * (len(plaintext) - 4)}{plaintext[-4:]}"
