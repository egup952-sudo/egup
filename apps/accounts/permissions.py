"""
Single place that enforces RBAC. Every admin view must use one of these —
that consistency is what replaces the RLS backstop Supabase used to provide.
"""
from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse


def _get_admin_profile(user):
    if not user.is_authenticated:
        return None
    return getattr(user, "admin_profile", None)


def require_permission(codename: str):
    """View decorator: 403s (raises PermissionDenied) unless the logged-in
    user has an active AdminProfile whose role grants `codename`."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('accounts:dashboard_login')}?next={request.path}")
            profile = _get_admin_profile(request.user)
            if profile is None or not profile.has_permission(codename):
                raise PermissionDenied(f"Missing permission: {codename}")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


class PermissionRequiredMixin(AccessMixin):
    """Class-based-view equivalent of require_permission."""

    required_permission: str = ""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('accounts:dashboard_login')}?next={request.path}")
        profile = _get_admin_profile(request.user)
        if profile is None or not profile.has_permission(self.required_permission):
            raise PermissionDenied(f"Missing permission: {self.required_permission}")
        return super().dispatch(request, *args, **kwargs)
