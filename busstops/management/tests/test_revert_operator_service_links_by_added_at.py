from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.test import SimpleTestCase
from django.utils import timezone


class FakeCursor:
    def __init__(self, *, setting="on", rows=None):
        self.setting = setting
        self.rows = rows or []
        self.executed = []
        self.fetch_mode = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "current_setting('track_commit_timestamp'" in sql:
            self.fetch_mode = "setting"
        else:
            self.fetch_mode = "rows"

    def fetchone(self):
        if self.fetch_mode == "setting":
            return (self.setting,)
        return None

    def fetchall(self):
        if self.fetch_mode == "rows":
            return self.rows
        return []


class RevertOperatorServiceLinksByAddedAtTests(SimpleTestCase):
    command_name = "revert_operator_service_links_by_added_at"

    def make_operator(self):
        return Mock(pk="OP1", noc="OP1")

    def test_dry_run_reports_matching_links(self):
        added_at = timezone.now()
        fake_cursor = FakeCursor(
            rows=[(17, 101, "X1", "Town Centre", added_at)],
        )
        out = StringIO()

        with (
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.connection.vendor",
                "postgresql",
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.connection.cursor",
                return_value=fake_cursor,
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.connection.ops.quote_name",
                side_effect=lambda value: value,
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.Command.resolve_operator",
                return_value=self.make_operator(),
            ),
        ):
            call_command(
                self.command_name,
                operator="OP1",
                added_since="2026-05-10T10:00:00+01:00",
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Dry run: no links will be deleted.", output)
        self.assertIn("found 1 link(s)", output)
        self.assertIn("delete link 17", output)

    def test_apply_deletes_matching_links(self):
        fake_cursor = FakeCursor(
            rows=[(21, 202, "7", "Airport", timezone.now())],
        )
        delete_qs = Mock()
        delete_qs.delete.return_value = (1, {"busstops.Service_operator": 1})
        through_manager = Mock()
        through_manager.filter.return_value = delete_qs
        through_model = Mock()
        through_model.objects = through_manager
        through_model._meta.db_table = "busstops_service_operator"
        service_operator = Mock()
        service_operator.through = through_model
        out = StringIO()

        with (
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.connection.vendor",
                "postgresql",
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.connection.cursor",
                return_value=fake_cursor,
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.connection.ops.quote_name",
                side_effect=lambda value: value,
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.Command.resolve_operator",
                return_value=self.make_operator(),
            ),
            patch(
                "busstops.management.commands.revert_operator_service_links_by_added_at.Service.operator",
                service_operator,
            ),
        ):
            call_command(
                self.command_name,
                operator="OP1",
                added_since="2026-05-10T10:00:00+01:00",
                apply=True,
                stdout=out,
            )

        through_manager.filter.assert_called_once_with(id__in=[21])
        delete_qs.delete.assert_called_once_with()
        self.assertIn("Deleted 1 row(s)", out.getvalue())
