"""
RBAC for the admin dashboard.

Design notes (why this exists instead of relying on Django's built-in
is_staff/is_superuser only):

- Project B (Supabase) enforced roles two ways: an `admin_users.role` column
  checked in application code, AND Postgres Row Level Security policies as a
  second, database-level backstop. Supabase/RLS is gone, so that backstop is
  gone too — which means the application-level check here has to be taken
  seriously and applied consistently (via the decorators/mixins below), not
  bypassed by any view that forgets to check.

- Permissions are granular strings (e.g. "members.edit"), matching section 23
  of the migration brief, not just five hardcoded roles with baked-in logic.
  Roles are just named bundles of permissions, editable by a SUPER_ADMIN
  without a code change.

Never rely on `is_staff` alone to decide what an admin can do — it only
controls access to /django-admin/, not to this platform's own admin area.
"""
from django.conf import settings
from django.db import models


class Permission(models.Model):
    """A single granular capability, e.g. 'members.edit', 'payments.reconcile'."""

    codename = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["codename"]

    def __str__(self):
        return self.codename


class Role(models.Model):
    """A named bundle of permissions. Seeded defaults: SUPER_ADMIN,
    CONTENT_ADMIN, MEMBERSHIP_ADMIN, FINANCE_ADMIN, VIEWER (see
    apps/accounts/management/commands/seed_roles.py)."""

    name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)
    is_system_role = models.BooleanField(
        default=False,
        help_text="System roles (seeded defaults) cannot be deleted from the admin UI.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def has_permission(self, codename: str) -> bool:
        return self.permissions.filter(codename=codename).exists()


class AdminProfile(models.Model):
    """Links a Django auth User to a Role. One profile per admin user.

    A regular Django `User` with no AdminProfile has NO access to the
    platform admin area, regardless of is_staff/is_superuser — the
    dashboard checks for an AdminProfile + specific permission, not for
    Django's built-in flags. Django superusers are only used for
    /django-admin/ (the framework's own admin), which is a separate,
    developer-only surface, not the platform's admin dashboard.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="admin_profile"
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="profiles")
    is_active = models.BooleanField(
        default=True,
        help_text="Deactivating here revokes dashboard access immediately without deleting the account.",
    )
    two_factor_enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.get_username()} ({self.role.name})"

    def has_permission(self, codename: str) -> bool:
        if not self.is_active:
            return False
        return self.role.has_permission(codename)
