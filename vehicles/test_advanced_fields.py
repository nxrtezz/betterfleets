from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

from vehicles.forms import EditVehicleForm
from vehicles.models import AdvancedField, Vehicle
from vehicles.utils import apply_revision, get_revision


class AdvancedFieldOptionalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        for order, (name, slug, field_type) in enumerate(
            (
                ("Coachbuilder", "coachbuilder", AdvancedField.FieldType.TEXT),
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

    def test_advanced_values_are_saved_to_the_vehicle(self):
        form = EditVehicleForm(
            QueryDict(
                "advanced_coachbuilder=Wright&advanced_open-top=on"
                "&advanced_delivered=2020-01-02&summary=advanced"
            ),
            user=self.user,
            vehicle=self.vehicle,
            sibling_vehicles=Vehicle.objects.none(),
            advanced=True,
        )
        self.assertTrue(form.is_valid(), form.errors)

        revision, features = get_revision(
            self.vehicle, {"advanced": form.get_advanced_field_updates()}
        )
        revision.created_at = timezone.now()
        revision.save()
        apply_revision(revision, features)

        self.vehicle.refresh_from_db()
        self.assertEqual(
            self.vehicle.advanced,
            {"coachbuilder": "Wright", "open-top": True, "delivered": "2020-01-02"},
        )
