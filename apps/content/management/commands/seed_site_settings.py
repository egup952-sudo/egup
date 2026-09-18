from django.core.management.base import BaseCommand

from apps.content.default_legal_content import PRIVACY_POLICY_DEFAULT, TERMS_OF_USE_DEFAULT
from apps.content.models import SiteSetting


class Command(BaseCommand):
    help = (
        "Fills in default Privacy Policy / Terms of Use content if the SiteSetting "
        "row already exists but those fields are still blank (e.g. migrated before "
        "the defaults were added). Never overwrites existing content — safe to re-run."
    )

    def handle(self, *args, **options):
        settings_obj = SiteSetting.get_solo()
        changed = []

        if not settings_obj.privacy_policy_content.strip():
            settings_obj.privacy_policy_content = PRIVACY_POLICY_DEFAULT
            changed.append("privacy_policy_content")
        if not settings_obj.terms_content.strip():
            settings_obj.terms_content = TERMS_OF_USE_DEFAULT
            changed.append("terms_content")

        if changed:
            settings_obj.save(update_fields=changed)
            self.stdout.write(self.style.SUCCESS(f"Filled in: {', '.join(changed)}"))
        else:
            self.stdout.write("Privacy/Terms content already present — nothing changed.")
