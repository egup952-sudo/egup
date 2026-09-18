from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import AdminProfile, Role

User = get_user_model()


class Command(BaseCommand):
    help = (
        "Create the very first EGUP admin account (Django superuser + "
        "AdminProfile with the SUPER_ADMIN role) in one step. Run "
        "seed_roles first. After this, every other admin can be created "
        "through the dashboard's own Admin Users screen instead."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", default="")
        parser.add_argument("--password", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["username"]
        password = options["password"]

        if len(password) < 10:
            raise CommandError("Password must be at least 10 characters.")

        try:
            role = Role.objects.get(name="SUPER_ADMIN")
        except Role.DoesNotExist:
            raise CommandError("SUPER_ADMIN role not found — run `python manage.py seed_roles` first.")

        if User.objects.filter(username=username).exists():
            raise CommandError(f"A user named '{username}' already exists.")

        user = User.objects.create_superuser(username=username, email=options["email"], password=password)
        AdminProfile.objects.create(user=user, role=role)

        self.stdout.write(self.style.SUCCESS(
            f"Created superuser '{username}' with SUPER_ADMIN dashboard access. "
            f"Log in at {'{'}ADMIN_ROUTE_PREFIX{'}'}/login/ and change this password."
        ))
