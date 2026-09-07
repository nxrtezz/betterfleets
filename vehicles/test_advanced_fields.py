from django.contrib.auth import get_user_model
from django.test import TestCase

from vehicles.forms import EditVehicleForm
from vehicles.models import AdvancedField, Vehicle


class AdvancedFieldOptionalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        for order, (name, slug, field_type) in enumerate(
            (
                ("Engine", "engine", AdvancedField.FieldType.TEXT),
                (
                    "Seating capacity",
                    "seating-capacity",
                    AdvancedField.FieldType.NUMBER,
                ),
                ("Open top", "open-top", AdvancedField.FieldType.BOOLEAN),
                ("Delivered", "delivered", AdvancedField.FieldType.DATE),
                ("Photo", "photo", AdvancedField.FieldType.URL),
            )
        ):
            AdvancedField.objects.create(
                name=name, slug=slug, field_type=field_type, display_order=order
            )
        cls.vehicle = Vehicle.objects.create(code="1", reg="AB12CDE")
        cls.user = get_user_model().objects.create_user(
            username="editor", email="editor@example.com", password="secret"
        )

    def test_advanced_fields_are_optional(self):
        form = EditVehicleForm(
            None,
            user=self.user,
            vehicle=self.vehicle,
            sibling_vehicles=Vehicle.objects.none(),
            advanced=True,
        )

        self.assertTrue(form.advanced_fields)
        for field_name in form.advanced_field_fields:
            self.assertFalse(form.fields[field_name].required, field_name)
