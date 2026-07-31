from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fleet.discord_bot import build_bot


class Command(BaseCommand):
    help = "Run the Better Fleets Discord bot."

    def handle(self, *args, **options):
        if not settings.DISCORD_BOT_TOKEN:
            raise CommandError("DISCORD_BOT_TOKEN is not configured.")

        bot = build_bot()
        bot.run(settings.DISCORD_BOT_TOKEN)
