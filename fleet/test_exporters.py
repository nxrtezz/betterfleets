from django.test import TestCase

from busstops.models import Operator
from fleet.exporters.xlsx import build_basic_fleet_workbook
from vehicles.models import AdvancedField, Vehicle


class AdvancedFleetExportTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = Operator.objects.create(name="Advanced Operator", noc="ADV")
        AdvancedField.objects.create(name="Engine", slug="engine", display_order=1)
        AdvancedField.objects.create(
            name="Seating capacity",
            slug="seating-capacity",
            field_type=AdvancedField.FieldType.NUMBER,
            display_order=2,
        )
        AdvancedField.objects.create(
            name="Open top",
            slug="open-top",
            field_type=AdvancedField.FieldType.BOOLEAN,
            display_order=3,
        )
        cls.vehicle = Vehicle.objects.create(
            code="1",
            operator=cls.operator,
            reg="AB12CDE",
            advanced={"engine": "Cummins", "open-top": True},
        )

    @staticmethod
    def cells(worksheet, row_number):
        values = [cell.value for cell in worksheet[row_number]]
        while values and values[-1] is None:
            values.pop()
        return values

    def test_every_advanced_field_gets_a_column(self):
        worksheet = build_basic_fleet_workbook(
            self.operator, [self.vehicle], advanced=True
        ).active

        expected = list(
            AdvancedField.objects.order_by("display_order", "name").values_list(
                "name", flat=True
            )
        )
        headers = self.cells(worksheet, 4)
        self.assertEqual(headers[6:], expected)

        row = self.cells(worksheet, 5)
        values = dict(zip(headers[6:], row[6:]))
        self.assertEqual(values["Engine"], "Cummins")
        self.assertEqual(values["Open top"], "Yes")
        self.assertEqual(values["Seating capacity"], "")

    def test_basic_export_has_no_advanced_columns(self):
        worksheet = build_basic_fleet_workbook(
            self.operator, [self.vehicle], advanced=False
        ).active

        self.assertEqual(self.cells(worksheet, 4)[-1], "Features")
