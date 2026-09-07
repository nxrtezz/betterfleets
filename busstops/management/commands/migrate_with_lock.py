from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

LOCK_ID = 4297151


class Command(BaseCommand):
    help = """Migrate while holding a Postgres advisory lock,
so several containers starting at once don't migrate concurrently"""

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            call_command("migrate", interactive=False)
            return

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [LOCK_ID])
            try:
                call_command("migrate", interactive=False)
            finally:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
