from unittest.mock import patch
from django.contrib.auth.models import Group, Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, OperatorUser
from busstops.models import Operator
from vehicles.models import Vehicle, VehicleRevision
from vehicles.permissions import can_auto_approve_revision, can_review_revision


class EditApprovalTest(TestCase):
    def setUp(self):
        self.a = Operator.objects.create(noc='AAAA')
        self.b = Operator.objects.create(noc='BBBB')
        self.vehicle = Vehicle.objects.create(operator=self.a, code='1', slug='approval-test')
        self.author = User.objects.create(username='author',email='author@example.test')
        self.trusted = User.objects.create(username='trusted',email='trusted@example.test',trusted=True)
        self.operator_user = User.objects.create(username='operator',email='operator@example.test')
        OperatorUser.objects.create(user=self.operator_user,operator=self.a)
        self.reviewer = User.objects.create(username='reviewer',email='reviewer@example.test')
        self.reviewer.groups.add(Group.objects.get(name='edits'))
        self.revision = VehicleRevision.objects.create(vehicle=self.vehicle,user=self.author,
            created_at=timezone.now(),pending=True,changes={'notes':'-\n+test'})

    def post(self,user,action='apply'):
        self.client.force_login(user)
        return self.client.post(reverse('vehicle_revision_action',args=[self.revision.pk,action]))

    def test_trusted_does_not_grant_reviewing_others(self):
        self.assertFalse(can_review_revision(self.trusted,self.revision))
        self.assertEqual(self.post(self.trusted).status_code,403)
        self.assertEqual(self.post(self.trusted,'disapprove').status_code,403)
        self.revision.refresh_from_db()
        self.assertTrue(self.revision.pending)

    def test_trusted_only_auto_approves_own_submission(self):
        self.assertFalse(can_auto_approve_revision(self.trusted,self.revision))
        self.revision.user=self.trusted
        self.assertTrue(can_auto_approve_revision(self.trusted,self.revision))

    def test_operator_user_auto_approval_is_scoped_and_own_only(self):
        self.assertFalse(can_auto_approve_revision(self.operator_user,self.revision))
        self.revision.user=self.operator_user
        self.assertTrue(can_auto_approve_revision(self.operator_user,self.revision))
        self.revision.to_operator=self.b
        self.assertFalse(can_auto_approve_revision(self.operator_user,self.revision))

    def test_operator_user_can_review_other_authors_within_scope(self):
        with patch('vehicles.views.apply_revision') as apply:
            self.assertEqual(self.post(self.operator_user).status_code,200)
            apply.assert_called_once()
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.approved_by_id,self.operator_user.pk)
        self.assertFalse(self.revision.pending)

    def test_operator_cannot_review_another_operator_or_unilateral_transfer(self):
        self.revision.to_operator=self.b
        self.revision.save()
        self.assertEqual(self.post(self.operator_user).status_code,403)
        self.vehicle.operator=self.b
        self.vehicle.save()
        self.revision.to_operator=None
        self.revision.save()
        self.assertEqual(self.post(self.operator_user,'disapprove').status_code,403)

    def test_edits_group_grants_global_moderation(self):
        self.assertTrue(self.reviewer.has_perm('vehicles.approve_vehicle_edits'))
        self.assertEqual(self.post(self.reviewer,'disapprove').status_code,200)
        self.revision.refresh_from_db()
        self.assertTrue(self.revision.disapproved)

    def test_invalid_action_cannot_mutate_revision(self):
        self.assertEqual(self.post(self.reviewer,'anything').status_code,400)
        self.revision.refresh_from_db()
        self.assertIsNone(self.revision.approved_by_id)

    def test_author_can_cancel_pending_edit(self):
        self.assertEqual(self.post(self.author,'disapprove').status_code,200)
        self.assertFalse(VehicleRevision.objects.filter(pk=self.revision.pk).exists())

    def test_trusted_cannot_see_review_buttons(self):
        from django.template.loader import render_to_string
        html=render_to_string('vehicle_revision.html',{'revision':self.revision,'user':self.trusted})
        self.assertNotIn('Apply changes',html)
        self.assertNotIn('Decline</button>',html)
