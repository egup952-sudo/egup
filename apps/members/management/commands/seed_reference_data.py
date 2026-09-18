from django.core.management.base import BaseCommand

from apps.members.models import Church, County, Department, Profession, Skill

# Exact lists carried over from the original frontend's
# assets/js/reference-data.js FALLBACK_* constants, so the dropdowns show
# the same options the original site always showed.
COUNTIES = [
    "Mombasa", "Kwale", "Kilifi", "Tana River", "Lamu", "Taita-Taveta", "Garissa", "Wajir",
    "Mandera", "Marsabit", "Isiolo", "Meru", "Tharaka-Nithi", "Embu", "Kitui", "Machakos",
    "Makueni", "Nyandarua", "Nyeri", "Kirinyaga", "Murang'a", "Kiambu", "Turkana", "West Pokot",
    "Samburu", "Trans Nzoia", "Uasin Gishu", "Elgeyo-Marakwet", "Nandi", "Baringo", "Laikipia",
    "Nakuru", "Narok", "Kajiado", "Kericho", "Bomet", "Kakamega", "Vihiga", "Bungoma", "Busia",
    "Siaya", "Kisumu", "Homa Bay", "Migori", "Kisii", "Nyamira", "Nairobi City",
]
DEPARTMENTS = ["Music", "Media", "Intercessory", "Usher and Protocol", "Evangelism"]
PROFESSIONS = [
    "Teacher", "Nurse", "Doctor", "Engineer", "Accountant", "Farmer", "Business Person",
    "Student", "Driver", "Electrician", "Mechanic", "Pastor / Clergy", "Lawyer", "Civil Servant", "Other",
]
SKILLS = [
    "Computer / ICT", "Photography", "Graphic Design", "Public Speaking", "Music / Singing",
    "Counseling", "First Aid", "Driving", "Catering", "Tailoring", "Carpentry", "Videography",
    "Writing", "Event Planning", "Other",
]
CHURCHES = ["Bless A Soul Family Church"]


class Command(BaseCommand):
    help = "Seed counties/churches/professions/skills/departments matching the original frontend's reference data. Safe to re-run."

    def handle(self, *args, **options):
        for name in COUNTIES:
            County.objects.get_or_create(name=name)
        for name in CHURCHES:
            Church.objects.get_or_create(name=name)
        for name in PROFESSIONS:
            Profession.objects.get_or_create(name=name)
        for name in SKILLS:
            Skill.objects.get_or_create(name=name)
        for name in DEPARTMENTS:
            Department.objects.get_or_create(name=name)
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(COUNTIES)} counties, {len(CHURCHES)} churches, {len(PROFESSIONS)} professions, "
            f"{len(SKILLS)} skills, {len(DEPARTMENTS)} departments."
        ))
