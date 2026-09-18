from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Permission, Role

PERMISSIONS = [
    ("dashboard.view", "View the admin dashboard"),
    ("members.view", "View members"), ("members.edit", "Edit members"), ("members.export", "Export member data"),
    ("payments.view", "View payments"), ("payments.reconcile", "Reconcile/investigate payments"),
    ("payments.export", "Export payment reports"),
    ("content.view", "View content"), ("content.create", "Create content"),
    ("content.edit", "Edit content"), ("content.publish", "Publish/unpublish content"), ("content.delete", "Delete content"),
    ("media.upload", "Upload media"), ("media.delete", "Delete media"),
    ("events.manage", "Manage events"), ("announcements.manage", "Manage announcements"),
    ("admins.manage", "Manage admin users and roles"),
    ("security.view", "View security/audit logs"),
    ("settings.manage", "Manage system settings"),
    ("payments.credentials", "View/change payment provider credentials (PayHero, M-Pesa)"),
]

ROLES = {
    "SUPER_ADMIN": [p[0] for p in PERMISSIONS],  # everything
    "CONTENT_ADMIN": ["dashboard.view", "content.view", "content.create", "content.edit",
                       "content.publish", "content.delete", "media.upload", "media.delete",
                       "events.manage", "announcements.manage"],
    "MEMBERSHIP_ADMIN": ["dashboard.view", "members.view", "members.edit", "members.export"],
    "FINANCE_ADMIN": ["dashboard.view", "payments.view", "payments.reconcile", "payments.export",
                       "payments.credentials"],
    "VIEWER": ["dashboard.view", "members.view", "payments.view", "content.view", "security.view"],
}


class Command(BaseCommand):
    help = "Seed the default granular permissions and roles (brief section 23). Safe to re-run."

    @transaction.atomic
    def handle(self, *args, **options):
        for codename, description in PERMISSIONS:
            Permission.objects.update_or_create(codename=codename, defaults={"description": description})

        for role_name, perm_codenames in ROLES.items():
            role, _ = Role.objects.update_or_create(
                name=role_name, defaults={"is_system_role": True}
            )
            perms = Permission.objects.filter(codename__in=perm_codenames)
            role.permissions.set(perms)
            self.stdout.write(self.style.SUCCESS(f"Seeded role {role_name} with {perms.count()} permissions"))

        self.stdout.write(self.style.SUCCESS("Done. Create a superuser, then attach an AdminProfile with a Role."))
