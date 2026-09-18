# EGUP Platform — Audit Checklist (Phase A deliverable)

This is the formal checklist the migration brief asked for as its own
artifact. Status reflects the current state of the codebase, honestly —
"Fixed" means code exists and was reasoned through carefully; it does
NOT mean verified by an actual test run (see PROGRESS.md's repeated
caveat: no network access in this sandbox, nothing has run through a
real Django process at any point in this project).

## 🔴 CRITICAL

| Item | Status |
|---|---|
| Manual payment `OneToOneField` blocked resubmission after rejection | **Fixed** — changed to `ForeignKey`, full attempt history preserved |
| Payment status/manual-submit endpoints trusted UUID alone as authorization | **Fixed** — hashed access token issued at creation, required on both endpoints |
| Manual payment screenshot upload only checked "file present," not actual content | **Fixed** — now runs through the same Pillow-based validator gallery/hero uploads use |
| Payment screenshots served from public `/media/` with no authorization | **Fixed** — RBAC-gated Django view instead |
| No backend enforcement on payment initiation frequency (frontend-only) | **Fixed** — phone-scoped rate limit, one-active-payment-per-registration check |

## 🟠 HIGH

| Item | Status |
|---|---|
| `manage.py check --deploy` never run | **Not done** — no network access in this sandbox at any point |
| Migrations never generated/applied against a real database | **Not done** — same reason; delete-and-regenerate instructions in `PROGRESS.md`/`DEPLOYMENT.md` |
| Rate limiting uses per-process `LocMemCache`, not shared across workers | **Known limitation, documented** — fine for launch scale, needs Redis for real multi-worker protection |
| Screenshot serving streams through the Django app process | **Known limitation, documented** — fine for launch scale, not for heavy traffic (nginx X-Accel-Redirect or signed S3 URLs would be the real fix) |
| Daraja provider is a stub | **Correctly left as a stub, not claimed complete** |

## 🟡 MEDIUM

| Item | Status |
|---|---|
| No 2FA for high-privilege admins | **Not implemented** — spec listed this as "if feasible" |
| No receipt PDF generation | **Not implemented**, deferred |
| No SMS/email/WhatsApp notifications | **Not implemented**, deferred (architecture doesn't block adding it later — every triggering event already goes through `log_action`) |
| No dedicated daily/weekly/monthly report screens | **Not implemented** — CSV export exists, has the data, no pre-built report UI |
| Privacy Policy / Terms content is a real draft, not legally reviewed | **Flagged explicitly in the content itself** — get an actual review before launch |

## 🟢 LOW

| Item | Status |
|---|---|
| No Cloudflare API health panel in the dashboard | **Not built** |
| Groups (Judah/Joshua/Esther/Ezra/Gideon) had no descriptions available | **Displayed cleanly, extensible for future descriptions — no fabricated copy, per instruction** |
| Foundation scripture text (only references given, not verse wording) | **Only references displayed — no invented quotations, per instruction** |

## Security review sweep (spec sections 13–15)

- **SQL injection**: entire codebase uses Django ORM (`.filter()`,
  `.get()`, etc.). Swept for `cursor.execute`, `.raw(`, `.extra(`,
  `RawSQL`, and string-formatted SQL — none found anywhere in `apps/`.
- **XSS**: Django template auto-escaping is on everywhere (never
  disabled globally). Swept for `|safe` and found it used nowhere in
  `templates/`. Admin-authored content (announcements, event
  descriptions, page blocks) renders through the `linebreaks` filter,
  which escapes first — no raw HTML injection path exists for any
  admin-editable content field.
- **CSRF**: Django's CSRF middleware is on globally.
  `@csrf_exempt` appears in exactly one place — the PayHero payment
  callback (`apps/payments/views.py`), which is a legitimate case (an
  external server POST, not a browser request) and is protected instead
  by the per-payment `callback_token`, not by weakening CSRF as a
  workaround.

## What Phase A did NOT produce, said plainly

This checklist itself is the Phase A deliverable, produced after most of
the fixes rather than strictly before, since earlier passes in this
project's history moved straight into implementation. Going forward,
treat this file as living — update it as new issues are found or fixed,
rather than treating any status here as final until section "🟠 HIGH"'s
verification gap is closed by an actual test run.
