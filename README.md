# EGUP Platform

The EGUP public website, membership registration/renewal, and admin
dashboard — one Django project, one PostgreSQL database, PayHero for
M-Pesa payments. Supabase and the old Cloudflare Worker have been fully
retired; see `PROGRESS.md` for the migration history.

## 1. Local setup (development/testing)

```bash
pip install -r requirements.txt
cp .env.example .env          # the SECRET_KEY line at the top is enough to start locally
python manage.py makemigrations
python manage.py migrate
python manage.py seed_roles              # creates the 5 admin roles + permissions
python manage.py seed_reference_data     # counties/churches/skills/professions/departments
python manage.py seed_gallery            # real photos into the gallery + a default hero slide
python manage.py bootstrap_admin --username admin --password <a-real-password>
python manage.py test
python manage.py runserver
```

- Public site: http://localhost:8000/
- Admin dashboard: http://localhost:8000/dashboard/login/ (or whatever
  `ADMIN_ROUTE_PREFIX` is set to — see `.env.example`)

No PayHero/Postgres/Cloudflare setup is required just to browse the site
locally — SQLite is used automatically when `DATABASE_URL` isn't set.
The payment flow itself (registration/renewal) needs real PayHero
sandbox credentials to actually complete — see section 4.

There is **no hardcoded default admin account or password anywhere in
this project.** `bootstrap_admin` is the only way to create the first
one, and you choose the password yourself.

## 2. Project layout

```
apps/
  accounts/       admin users, roles/permissions (RBAC), dashboard login
  members/        Member, RegistrationIntent, registration wizard API,
                  reference data (counties/churches/skills/...)
  memberships/    membership periods (renewal history, never overwritten)
  payments/       Payment state machine, PayHero integration, credentials
  content/        hero slides, dynamic pages, site settings, contact form
  media_lib/      gallery / uploaded images
  events/         events
  announcements/  announcements
  audit/          audit log used across every app
  monitoring/     security headers, IP blocking, rate limiting
templates/
  public/         the public website (restored from the original frontend)
  admin_dashboard/ the admin dashboard
static/           CSS/JS/images (original site's real assets)
```

## 3. Admin dashboard

Log in at `<ADMIN_ROUTE_PREFIX>/login/`. What each role can do is
defined in `apps/accounts/management/commands/seed_roles.py` — edit and
re-run that command to change permission sets. New admin accounts are
created from inside the dashboard itself (Admin Users) after the first
one exists via `bootstrap_admin`.

## 4. Payments (PayHero)

Set PayHero credentials either as environment variables (`PAYHERO_*` in
`.env.example`) **or** from the dashboard under Finance > Payment
Credentials, which stores them encrypted in the database (not
plaintext) — the dashboard takes priority when both are set. Either way
requires `FIELD_ENCRYPTION_KEY` if using the dashboard route; see
`.env.example` for how to generate one.

Daraja (secondary/fallback M-Pesa) has credential fields available but
`DarajaProvider` itself is an intentional stub — it is **not** wired up
or audited the way PayHero is. Do not treat it as production-ready.

## 5. Deployment

See `DEPLOYMENT.md` for the full production checklist (environment
variables, database, static/media files, PayHero callback URL,
Cloudflare, security headers).

## 6. Tests

```bash
python manage.py test
```
`apps/payments/tests.py` includes regression tests carried over from a
security audit of an earlier version of the payment integration
(no fabricated webhook signature check, correct provider reference
field, concurrent-callback race protection, amount-tampering
detection) — these are non-negotiable and should never be weakened.
