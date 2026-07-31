from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import User

from .models import EntityUserRole, Event, Operator, PreservationGroup


class EventModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.group = PreservationGroup.objects.create(
            name="Test Group",
            slug="test-group",
        )
        cls.operator = Operator.objects.create(noc="TEVT", name="Test Operator")

    def test_event_requires_owner(self):
        event = Event(
            slug="orphan-event",
            name="Orphan",
            start_date=date(2026, 1, 1),
        )
        with self.assertRaises(ValidationError):
            event.full_clean()

    def test_entity_user_role_required_with_user(self):
        user = User.objects.create(username="owner", email="owner@example.com")
        group = PreservationGroup(
            name="Owned Group",
            slug="owned-group",
            user=user,
        )
        with self.assertRaises(ValidationError):
            group.full_clean()

    def test_preservation_group_user_attribution(self):
        user = User.objects.create(
            username="manager",
            email="manager@example.com",
            display_name="Group Manager",
        )
        group = PreservationGroup.objects.create(
            name="Managed Group",
            slug="managed-group",
            user=user,
            user_role=EntityUserRole.MANAGES,
        )
        self.assertTrue(group.has_user_attribution)
        self.assertEqual(group.get_user_attribution_entity_label(), "preservation group")
