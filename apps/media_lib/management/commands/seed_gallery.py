"""
Seeds the gallery with the real photos that came with the original site
(static/images/gallery/*.jpg) as proper MediaAsset rows — not links to
the static files, actual copies into media storage, so each one is a
normal, independently deletable/replaceable gallery item exactly like
anything an admin uploads later (brief section 20/8: "gallery now should
have the existing image, admin can add more on top of that, admin can
delete the older ones").
"""
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand

from apps.content.models import HeroSlide
from apps.media_lib.models import MediaAsset

GALLERY_IMAGES = [
    ("community-crowd-drama.jpg", "Community drama ministry outreach"),
    ("dance-ministry.jpg", "EGUP dance ministry team"),
    ("fellowship-youth.jpg", "Youth fellowship gathering"),
    ("outreach-team.jpg", "Evangelism outreach team"),
    ("photography-team-outreach.jpg", "Photography team documenting an outreach"),
    ("prayer-walk-crowd.jpg", "Believers gathered for a prayer walk"),
    ("prayer-walk-street.jpg", "Prayer walk through town"),
    ("volunteer-team.jpg", "Community service volunteer team"),
    ("worship-praise-team.jpg", "Worship and praise team leading a session"),
    ("youth-gathering.jpg", "EGUP youth program gathering"),
    ("sports-outreach-briefing.jpg", "A community briefing before a sports outreach event"),
    ("sports-outreach-match.jpg", "Youth playing a football match during a sports outreach"),
    ("sports-outreach-youth.jpg", "Young people playing football together"),
    ("sports-outreach-team.jpg", "A team gathered during a sports outreach event"),
    ("sports-outreach-crowd.jpg", "Players and children on the field during an outreach match"),
    ("sports-outreach-action.jpg", "Action from a sports outreach match"),
    ("creative-expo-art.jpg", "A young artist showing his artwork at a creative expo"),
    ("creative-expo-showcase.jpg", "A showcase moment at a creative and fashion expo"),
    ("creative-expo-celebration.jpg", "Celebration and dance at a community event"),
    ("creative-expo-fashion.jpg", "A moment from a fashion and creative expo"),
    ("creative-expo-display.jpg", "A creative display at an expo event"),
    ("fellowship-gathering-1.jpg", "Believers gathered together in fellowship"),
    ("fellowship-gathering-2.jpg", "A fellowship gathering moment"),
    ("fellowship-gathering-3.jpg", "Community members at a fellowship gathering"),
]

HERO_IMAGES = [
    ("hero-outreach-briefing.jpg", "Community leaders and youth gathered together before a sports outreach event",
     "Establishment. God Revealing Himself. Understanding His Word. Positioning Ourselves.",
     "EGUP mobilises believers across Kenya into evangelism, discipleship, prayer, worship and community outreach."),
    ("hero-street-outreach.jpg", "Believers carrying out a gospel outreach through the streets of town",
     "Carrying the Gospel to the Streets.",
     "Organised outreach drives into neighbourhoods, markets and public spaces, sharing the Gospel where people are."),
    ("hero-worship-gathering.jpg", "A worship team leading a gathering in praise and worship",
     "God Revealing Himself in Worship.",
     "Dedicated gatherings of praise and worship, creating space for God to move among His people."),
]


class Command(BaseCommand):
    help = "Seed the gallery and a default hero slide with the original site's real photos. Safe to re-run (skips images already seeded)."

    def handle(self, *args, **options):
        gallery_source = Path(settings.BASE_DIR) / "static" / "images" / "gallery"
        hero_source = Path(settings.BASE_DIR) / "static" / "images" / "hero"

        created_gallery = 0
        for filename, caption in GALLERY_IMAGES:
            if MediaAsset.objects.filter(category="GALLERY", caption=caption).exists():
                continue
            src_path = gallery_source / filename
            if not src_path.exists():
                self.stdout.write(self.style.WARNING(f"Skipping {filename} — not found at {src_path}"))
                continue
            with open(src_path, "rb") as fh:
                asset = MediaAsset(category="GALLERY", caption=caption, alt_text=caption, is_published=True)
                asset.file.save(filename, File(fh), save=True)
            created_gallery += 1

        created_hero = 0
        if not HeroSlide.objects.exists():
            for filename, alt_text, title, subtitle in HERO_IMAGES:
                src_path = hero_source / filename
                if not src_path.exists():
                    self.stdout.write(self.style.WARNING(f"Skipping {filename} — not found at {src_path}"))
                    continue
                with open(src_path, "rb") as fh:
                    asset = MediaAsset(category="HERO", alt_text=alt_text, is_published=True)
                    asset.file.save(filename, File(fh), save=True)
                HeroSlide.objects.create(title=title, subtitle=subtitle, image=asset, is_active=True, display_order=created_hero)
                created_hero += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {created_gallery} gallery image(s) and {created_hero} hero slide(s). "
            f"Already-seeded images were skipped, not duplicated."
        ))
