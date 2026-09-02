# Adds Request.photo_url / HistoricalRequest.photo_url /
# HistoricalRequest.history_relation_id.
#
# These fields exist on the models (Request.photo_url, and the
# HistoricalRecords(related_name="request_history") option which adds
# "history_relation" to HistoricalRequest) but were never captured in
# 0002_request_historical.py, so some databases are missing the columns.
# Written defensively so it is a no-op wherever a column already exists.

from django.db import migrations


def _column_exists(cursor, table, column):
    cursor.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=%s AND column_name=%s",
        [table, column],
    )
    return cursor.fetchone() is not None


def add_missing_columns(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if not _column_exists(cursor, "service_requests_request", "photo_url"):
            cursor.execute(
                'ALTER TABLE "service_requests_request" '
                'ADD COLUMN "photo_url" varchar(200) NOT NULL DEFAULT \'\''
            )
            cursor.execute(
                'ALTER TABLE "service_requests_request" '
                'ALTER COLUMN "photo_url" DROP DEFAULT'
            )

        if not _column_exists(
            cursor, "service_requests_historicalrequest", "photo_url"
        ):
            cursor.execute(
                'ALTER TABLE "service_requests_historicalrequest" '
                'ADD COLUMN "photo_url" varchar(200) NOT NULL DEFAULT \'\''
            )
            cursor.execute(
                'ALTER TABLE "service_requests_historicalrequest" '
                'ALTER COLUMN "photo_url" DROP DEFAULT'
            )

        if not _column_exists(
            cursor, "service_requests_historicalrequest", "history_relation_id"
        ):
            cursor.execute(
                'ALTER TABLE "service_requests_historicalrequest" '
                'ADD COLUMN "history_relation_id" integer NULL'
            )
            # Historical rows mirror the original object's primary key in
            # their own "id" column, so that's also the correct backfill
            # value for the new self-referencing "history_relation" field.
            cursor.execute(
                'UPDATE "service_requests_historicalrequest" '
                'SET "history_relation_id" = "id" '
                'WHERE "history_relation_id" IS NULL'
            )
            cursor.execute(
                'CREATE INDEX '
                '"service_requests_historicalrequest_history_relation_id_idx" '
                'ON "service_requests_historicalrequest" ("history_relation_id")'
            )


class Migration(migrations.Migration):

    dependencies = [
        ("service_requests", "0002_request_historical"),
    ]

    operations = [
        migrations.RunPython(add_missing_columns, migrations.RunPython.noop),
    ]
