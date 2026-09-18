def admin_profile(request):
    """Adds `admin_profile` (or None) to every template's context. Used by
    the dashboard shell (_base.html) to show the logged-in admin's name
    and role without every single admin view needing to pass it."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return {"current_admin_profile": getattr(user, "admin_profile", None)}
    return {"current_admin_profile": None}


def topbar_alerts(request):
    """Notification bell + mail icon badge counts (_base.html topbar), on
    every admin page, not just the dashboard home — same reasoning as
    active_nav below: one place, always correct, real queries, no
    per-view boilerplate. Only queries when logged in, since these
    tables are meaningless (and admin_profile is None) pre-login."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"topbar_notification_count": 0, "topbar_unread_messages": 0}

    from apps.content.models import ContactMessage
    from apps.payments.models import ManualPaymentSubmission, Payment

    notification_count = (
        ManualPaymentSubmission.objects.filter(verification_status="PENDING").count()
        + Payment.objects.filter(status="SUSPICIOUS").count()
    )
    unread_messages = ContactMessage.objects.filter(is_read=False).count()
    return {"topbar_notification_count": notification_count, "topbar_unread_messages": unread_messages}


_NAMESPACE_TO_NAV_KEY = {
    "accounts": "dashboard",  # overridden below for admins:* views specifically
    "members_admin": "members",
    "payments_admin": "payments",
    "events_admin": "events",
    "announcements_admin": "announcements",
    "media_lib_admin": "gallery",
    "content_admin": "hero",  # overridden below per url_name
    "audit_admin": "audit",
}

_URLNAME_OVERRIDES = {
    "dashboard_home": "dashboard",
    "admin_list": "admins", "admin_create": "admins", "admin_edit": "admins",
    "site_settings": "site_settings",
    "page_list": "pages", "page_create": "pages", "page_edit": "pages",
    "credentials": "credentials",
    "settings": "payment_settings",
    "manual_verification_queue": "manual_verification",
    "manual_verification_verify": "manual_verification",
    "manual_verification_reject": "manual_verification",
    "manual_verification_flag": "manual_verification",
    "message_list": "messages",
    "social_link_list": "social_links", "social_link_create": "social_links",
    "social_link_edit": "social_links", "social_link_delete": "social_links",
    "reference_list": None,  # handled via the `kind` URL kwarg instead
    "reference_create": None, "reference_edit": None,
}


def active_nav(request):
    """Derives which sidebar link should be highlighted from the current
    URL, so individual admin views don't each need to pass an `active`
    context variable by hand — one place, always correct, covers new
    admin views automatically as they're added."""
    match = getattr(request, "resolver_match", None)
    if match is None:
        return {"active": None}

    if match.namespace == "members_admin" and match.url_name in ("reference_list", "reference_create", "reference_edit"):
        return {"active": match.kwargs.get("kind")}

    if match.url_name == "search":
        return {"active": None}  # not a sidebar item — no highlight, don't fall through to Dashboard

    key = _URLNAME_OVERRIDES.get(match.url_name)
    if key is not None:
        return {"active": key}
    if match.url_name in _URLNAME_OVERRIDES:  # explicitly mapped to None above — fall through to namespace
        pass
    return {"active": _NAMESPACE_TO_NAV_KEY.get(match.namespace)}
