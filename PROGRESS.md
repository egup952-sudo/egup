# EGUP Platform — Progress

No live data exists — data-migration phase dropped entirely.

## This pass: frontend phases (H-L), matching the spec's exact given wording

Read `/mnt/skills/user/egup-platform-engineering/SKILL.md` in full per
your request — it reaffirms the approach already followed throughout
this project (preserve the original frontend, Django as backend,
PayHero/M-Pesa security, real admin dashboard, RBAC). No course
correction needed; continued the payment UX work already in progress.
Note: `/egup-frontend-design` doesn't exist as an actual file in this
environment, only `egup-platform-engineering` does.

### Payment UX (spec section 34/35/36) — now matches the spec's exact copy
- Payment method choice is now two real selection cards, not plain
  buttons: **"M-Pesa Express" / "Receive a payment prompt on your
  phone."** and **"Pay via M-Pesa PayBill" / "Already paid? Submit your
  transaction details for verification."** — the spec's own wording,
  used verbatim rather than paraphrased.
- Loading states aligned to the spec's exact examples: "Submitting
  registration...", "Initiating M-Pesa payment...", "Waiting for M-Pesa
  confirmation...", "Submitting payment for verification..."
- Status wording aligned exactly: "Payment confirmed." (PAID), "We could
  not confirm the payment. Please try again." (FAILED), "Payment
  submitted. EGUP is reviewing your payment." (PENDING_VERIFICATION).
  Added a missing `.payment-status--success` CSS class the PAID case
  needed.

### Real gap closed: payment status polling didn't stop when the user left
Spec section 41 explicitly requires this. `pollPaymentStatus` now pauses
while the tab is backgrounded (`visibilitychange`) instead of continuing
to hit the backend for a page nobody is looking at, and resumes
automatically when the user comes back — still bounded by the same
overall timeout.

### More dashes found and fixed — a different pattern than before
Two earlier passes caught the `&mdash;` HTML entity and the literal `—`
Unicode character. This pass found a **third** pattern: JavaScript
string literals using the `\u2014` escape sequence, which neither
earlier grep caught. Found in `membership-registration.js`,
`renewal.js`, `gallery.js`, `contact.js` — three were genuine prose
connectors (reworded properly, not just deleted), and roughly a dozen
were the em-dash used as an empty-value placeholder in the registration
review screen (e.g. "Email: —" when a field was left blank) — replaced
with "N/A" for the same reason: still a dash character, still in scope
for "all of them." Code comments (`//` and `/* */`) still contain dashes
in a few places — left alone, since those are invisible to anyone
viewing the actual pages, not "frontend page" content.

## Phase A checklist status update

See `AUDIT_CHECKLIST.md` — no items changed status this pass; this was
purely frontend wording/UX work, no new security surface introduced.

## This pass, part 2: accessibility + mobile gaps found by checking, not assuming

- **Wizard step transitions never moved focus.** Clicking "Continue" hid
  the current step and showed the next one, but keyboard/screen-reader
  users stayed focused on the now-hidden button. `goToStep()` now moves
  focus to the new step's heading — a real multi-step-form accessibility
  gap, not a nice-to-have.
- **Payment status messages had no `aria-live` region.** Visually
  updating a status paragraph does nothing for a screen-reader user
  unless the browser is told to announce it. Added `role="status"
  aria-live="polite"` to all four payment-status paragraphs (automatic
  and manual, registration and renewal) — found by checking, since two
  of the four already had it from earlier work and two didn't.
- **Admin tables clipped data on mobile instead of scrolling.**
  `overflow: hidden` on `.table` (kept for the rounded-corner effect on
  desktop) was ALSO clipping wide tables — payments (7 columns), members
  — on narrow screens, cutting off data invisibly rather than making it
  scrollable. Fixed with a mobile-only override to a horizontally
  scrollable table.
- Checked and confirmed already solid, no changes needed: field-level
  error `aria-describedby`/`aria-invalid` wiring in the registration
  wizard, mobile hamburger menu's Escape-key/`aria-expanded` handling,
  admin list templates' empty states, `.grid-2`'s mobile-first responsive
  behavior, no fixed-width elements risking horizontal overflow anywhere
  in the public templates.

## This pass, part 3: reduced-motion, checked against the actual `frontend-design` skill's quality floor

`/egup-frontend-design` and `/egup-platform-upgrade` still don't exist as
files in this environment — checked again, only
`egup-platform-engineering` and the generic public `frontend-design`
skill are present. Applied the latter's explicit quality-floor
requirement ("reduced motion respected") by actually checking rather
than assuming the earlier CSS-level fix covered everything.

It didn't. The global CSS override (`animation-duration: 0.01ms` etc. in
`base.css`/`variables.css`) only catches CSS transitions/animations —
two things bypass it entirely because they're pure JavaScript:
- The homepage stat counter's count-up animation (`requestAnimationFrame`
  loop) — reduced-motion users were still getting the full 1.4s count-up.
  Now skips straight to the final number.
- Every `window.scrollTo({behavior: 'smooth'})` call (back-to-top button,
  the registration wizard's step-to-step scroll) — an explicit `behavior:
  'smooth'` argument in JS overrides the CSS `scroll-behavior:auto`
  fallback in most browsers; the CSS property only changes the *default*,
  it doesn't block an explicit request. New shared `smoothScrollTo()`
  helper in `main.js` (exposed as `window.egupPrefersReducedMotion` for
  other page scripts) checks the media query directly before deciding
  smooth vs. instant.
- Checked focus-visibility: two places suppress the default outline but
  both substitute a clearly visible border-color/box-shadow focus state
  instead (acceptable). One `outline: none` (the admin topbar search
  input) is harmless — the input is `disabled`, so it's never reachable
  by keyboard at all.
- **Flagging honestly, not fixing**: that admin topbar search input is
  disabled/decorative — it visually promises search but does nothing.
  Building real site-wide admin search (members, payments, events,
  content) is a genuine feature, not a quick styling fix; out of scope
  for this pass, noted here rather than left silently unnoticed.

## Still open (unchanged, still honest about it)

Daraja stub, 2FA, receipt PDFs, notifications, dedicated report screens,
Cloudflare health panel. And per your instruction, **testing (Phase M)
is explicitly left to you** — `manage.py check`, `check --deploy`,
`makemigrations --check`, `migrate`, `test` still need to run on a
machine with real access; see `DEPLOYMENT.md` and this file's earlier
entries for the exact command sequence.
