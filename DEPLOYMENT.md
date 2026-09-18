# EGUP Platform — Deployment Checklist

Concrete steps for a production deploy. Go in order; each section
depends on the one before it.

## 1. Before you deploy — required environment variables

Set these on your host (Railway, or wherever you deploy). None of them
should ever be committed to source control.

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | Yes | Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"`. As of this security hardening pass, the app refuses to start without this when `DEBUG=False` — it no longer silently falls back to an insecure default. |
| `DEBUG` | Yes | Must be `False` in production. As of this pass, unset now defaults to `False` (previously defaulted to `True`, which was backwards) — but set it explicitly regardless. |
| `ALLOWED_HOSTS` | Yes | Comma-separated, e.g. `egup.example.com,www.egup.example.com` |
| `CSRF_TRUSTED_ORIGINS` | Yes | Comma-separated, full origins with scheme, e.g. `https://egup.example.com` |
| `DATABASE_URL` | Yes | `postgres://user:pass@host:5432/dbname` — **must be Postgres in production**, per the brief. |
| `PAYHERO_API_USERNAME` / `PAYHERO_API_PASSWORD` / `PAYHERO_CHANNEL_ID` | Yes* | *Or set later via the dashboard's Payment Credentials screen (see below) — but at least one path must be configured before registration/renewal will work. |
| `PAYHERO_CALLBACK_BASE_URL` | Yes | Must be a real, publicly reachable HTTPS URL, e.g. `https://egup.example.com/payments/callback/payhero/` |
| `FIELD_ENCRYPTION_KEY` | Only if using the dashboard's Payment Credentials screen | Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `BEHIND_CLOUDFLARE` | Yes | `True` if Cloudflare is in front (see section 5). |
| `ADMIN_ROUTE_PREFIX` | Recommended | Change from the default `/dashboard/` to something org-specific but not secret-dependent (real protection is auth+RBAC, not the path). |
| `USE_S3_STORAGE` + `AWS_*` | Recommended | See section 4 — without this, uploaded media (gallery photos, hero slides, event images) lives on local disk and **will be lost on redeploy** on most PaaS hosts. |
| `REDIS_URL` | Yes | Added by this security hardening pass. Without it, rate limiting (payment attempts, OTP requests, login lockouts) falls back to per-process memory — meaningless with more than one gunicorn worker (this project runs `--workers 2`), since each worker keeps its own separate counters an attacker can bypass by spreading requests across them. Most hosts (Railway, Render) offer this as a one-click add-on that sets the variable for you. |
| `SMS_PROVIDER_CONFIGURED` | Only once you've wired in a real SMS gateway | See `apps/members/sms.py`. Renewal now requires a phone-verified OTP before it can be initiated (a membership number alone used to be enough to start a real payment against someone else's phone — fixed in this pass). Until a real provider is implemented in that file and this is set `True`, OTP codes go to your server logs instead of an actual phone — **renewal is not truly usable by real members until this is done.** |

Full list with comments: `.env.example`.

## 2. Database

```bash
python manage.py makemigrations --noinput
python manage.py migrate --noinput
python manage.py seed_roles
python manage.py seed_reference_data
python manage.py seed_gallery
python manage.py bootstrap_admin --username <you> --password <a-real-password>
```

The first three of these now run automatically on every deploy (see
`railway.toml`'s `startCommand`) — `makemigrations` because this project
generates migrations at deploy time rather than committing them (no
migration files exist in this repo for any app; `migrate` alone does
nothing without them), and `seed_roles` because it's idempotent
(`update_or_create` throughout) and needs to re-run whenever a
permission is added or changed, such as this pass's new
`payments.credentials` permission (previously bundled with
`settings.manage`, now separate — see the security audit). You only
need to run `seed_reference_data`, `seed_gallery`, and `bootstrap_admin`
by hand, and only once. `bootstrap_admin` only needs to run once ever —
every subsequent admin is created from inside the dashboard.

**This project has never been run against a real Django process in the
environment it was built in** (no network access in that sandbox). Treat
the very first deploy in production as a real test, not a formality —
watch the boot logs for migration errors before assuming it worked.

## 3. Static files

```bash
python manage.py collectstatic --noinput
```
WhiteNoise serves static files directly from the Django process — no
separate nginx/CDN config is required for this to work. `collectstatic`
uses `whitenoise.storage.CompressedManifestStaticFilesStorage`, which
**fails hard if any CSS/template references a static file that doesn't
exist**. If it fails, the error will name the missing file — check
`static/` for a typo'd path before assuming something deeper is wrong.

## 4. Media storage (uploaded images)

By default, uploaded files (gallery photos, hero slides, event images,
admin avatars if added later) go to local disk (`MEDIA_ROOT`). **On most
PaaS hosts (Railway included), local disk is wiped on every redeploy** —
meaning every image an admin uploads would vanish the next time you
push code. Before relying on the gallery/hero/events image upload
features in production, set:

```
USE_S3_STORAGE=True
AWS_STORAGE_BUCKET_NAME=...
AWS_S3_ENDPOINT_URL=...        # blank for real AWS S3; set for Backblaze B2/DO Spaces/Cloudflare R2/etc.
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_S3_REGION_NAME=...
```

If you deploy tomorrow without this configured, that's a known,
accepted gap — just don't be surprised when uploaded images disappear on
the next deploy. Local disk is fine for an initial launch if you're not
uploading gallery content on day one.

## 5. Cloudflare

Point Cloudflare's DNS at your app host, proxy enabled (orange cloud).
Then:
- Set `BEHIND_CLOUDFLARE=True`.
- **Firewall the origin server so only Cloudflare's IP ranges can reach
  it directly.** Without this, `apps/monitoring/ip_utils.py`'s trust of
  the `CF-Connecting-IP` header is meaningless — an attacker could hit
  your origin directly and spoof any IP they want in that header, since
  nothing would stop them from setting it themselves. This is an
  infrastructure step this codebase cannot enforce on its own; check
  your host's docs for "Cloudflare origin IP allowlist" or similar.
- Confirm `X-Forwarded-Proto` reaches Django correctly (test that
  `request.is_secure()` returns `True` for a normal HTTPS visit) —
  `SECURE_PROXY_SSL_HEADER` in `settings.py` depends on this.

## 6. PayHero callback URL

`PAYHERO_CALLBACK_BASE_URL` must point at a URL PayHero's servers can
actually reach — i.e. your real production domain, not `localhost`.
Test with a real (small) sandbox transaction before trusting the
registration/renewal flow end-to-end; the payment code in this project
has been carefully reasoned through against PayHero's documented API
shape but genuinely has **not** been exercised against a live PayHero
sandbox anywhere in this project's history — that first real transaction
is the actual test, not a formality.

## 7. Final checklist before calling it live

- [ ] `DEBUG=False` confirmed (visit a broken URL — you should see a
      plain error page, never a stack trace)
- [ ] `python manage.py check --deploy` run and reviewed (Django's own
      production-readiness checklist — this project has never had this
      run against it; do it before going live)
- [ ] A real PayHero sandbox transaction completed successfully end-to-end
- [ ] Admin dashboard reachable, `bootstrap_admin` account works, and a
      second admin created from Admin Users to confirm that flow too
- [ ] Gallery upload/delete tested for real (confirms media storage,
      whichever backend you chose, actually works)
- [ ] `/sitemap.xml` and `/robots.txt` both return valid content
- [ ] Privacy/Terms pages (`/privacy.html`, `/terms.html`) have real
      content filled in via Site Settings — they're empty placeholders
      until an admin fills them in
- [ ] Footer developer contact number displays correctly
- [ ] No admin link anywhere in public navigation (confirmed — see
      `templates/public/includes/header.html`/`footer.html`)
