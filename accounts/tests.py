from http import HTTPStatus
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from busstops.models import Operator
from fleet.models import FleetRideLog
from vehicles.models import Livery, Vehicle, VehicleReview, VehicleRevision

from .models import Invitation, ProfileTag, RegistrationSettings, User


class RegistrationTest(TransactionTestCase):
    def test_blank_email(self):
        with self.assertNumQueries(0):
            response = self.client.post("/accounts/register/")
        self.assertContains(response, "This field is required")

    @override_settings(
        # use an old, insecure password hasher, because it's fast
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    )
    def test_registration(self):
        dummy_uuid = "b4fcbc02-1920-4d0d-b07b-756db0cb2cd0"
        password = "swim green twenty eggs"
        reactivation_password = "purple candles at noon"
        mixed_case_password = "midnight depot lanterns"

        response = self.client.get(f"/accounts/register/?invite_code={dummy_uuid}")
        self.assertContains(response, "Email address")
        self.assertContains(response, "Password")
        self.assertContains(response, dummy_uuid)

        # no invite code
        response = self.client.post(
            "/accounts/register/",
            {
                "email": "rufus@herring.pizza",
                "password1": password,
                "password2": password,
                "invite_code": dummy_uuid,
            },
        )
        self.assertContains(response, "is not valid or has expired")

        invitation = Invitation.objects.create(
            uuid=dummy_uuid, expires_at="3000-01-01 00:00:00+00:00"
        )
        self.assertEqual(
            invitation.get_absolute_url(),
            f"/accounts/register/?invite_code={dummy_uuid}",
        )

        response = self.client.post(
            "/accounts/register/",
            {
                "email": "rufus@herring.pizza",
                "password1": password,
                "password2": password,
                "invite_code": dummy_uuid,
            },
            headers={"CF-Connecting-IP": "1.2.3.4"},
        )
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, "/vehicles")
        self.assertEqual([], mail.outbox)

        user = User.objects.get(email="rufus@herring.pizza")
        self.assertEqual(user.username, "rufus@herring.pizza")
        self.assertEqual(user.email, "rufus@herring.pizza")
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(password))
        self.assertEqual(str(user), f"user{user.id}")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.id))

        self.client.logout()
        user.is_active = False
        user.save(update_fields=["is_active"])

        response = self.client.post(
            "/accounts/register/",
            {
                "email": "RUFUS@HeRRInG.piZZa",
                "password1": reactivation_password,
                "password2": reactivation_password,
                "invite_code": dummy_uuid,
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, "/vehicles")

        user.refresh_from_db()
        self.assertEqual(user.username, "rufus@herring.pizza")
        self.assertEqual(user.email, "rufus@herring.pizza")
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password(reactivation_password))
        self.assertEqual(str(user), f"user{user.id}")
        self.assertEqual(self.client.session["_auth_user_id"], str(user.id))

        self.client.logout()

        response = self.client.post(
            "/accounts/register/",
            {
                "email": "ROY@HotMail.com",
                "password1": mixed_case_password,
                "password2": mixed_case_password,
                "invite_code": dummy_uuid,
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, "/vehicles")

        user = User.objects.get(email__iexact="ROY@HotMail.com")
        self.assertEqual(user.username, "ROY@HotMail.com")
        self.assertEqual(user.email, "ROY@hotmail.com")
        self.assertTrue(user.check_password(mixed_case_password))
        self.assertEqual(self.client.session["_auth_user_id"], str(user.id))
        self.assertEqual([], mail.outbox)

        self.client.logout()

        response = self.client.post(
            "/accounts/register/",
            {
                "email": "roy@hotmail.com",
                "password1": "double decker midnight tea",
                "password2": "double decker midnight tea",
                "invite_code": dummy_uuid,
            },
        )
        self.assertContains(response, "An account with that email address already exists")
        user.refresh_from_db()
        self.assertTrue(user.check_password(mixed_case_password))

        # username (email address) should be case insensitive
        data = {"username": "roY@hoTmail.com", "password": mixed_case_password}
        with self.assertNumQueries(9):
            response = self.client.post("/accounts/login/", data)
            self.assertEqual(302, response.status_code)

        # test CSDRF middeware
        csrf_client = Client(enforce_csrf_checks=True)
        with self.assertNumQueries(0), self.assertLogs():
            response = csrf_client.post("/accounts/login/", data)
        self.assertEqual(response.status_code, HTTPStatus.FORBIDDEN)

        csrf_client.force_login(user)
        with self.assertNumQueries(2), self.assertLogs():
            response = csrf_client.post("/accounts/login/", data)
        self.assertEqual(302, response.status_code)

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        NEW_USER_WEBHOOK_URL="https://discord.example/webhook",
    )
    @patch("accounts.notifications.requests.post")
    def test_registration_sends_webhook(self, mock_post):
        dummy_uuid = "24fddf5f-0609-4246-96f8-7b2f73d518a6"
        password = "tower bridge foghorn"
        Invitation.objects.create(
            uuid=dummy_uuid, expires_at="3000-01-01 00:00:00+00:00"
        )

        response = self.client.post(
            "/accounts/register/",
            {
                "email": "webhook@example.com",
                "password1": password,
                "password2": password,
                "invite_code": dummy_uuid,
            },
        )

        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        user = User.objects.get(email="webhook@example.com")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://discord.example/webhook")
        embed = kwargs["json"]["embeds"][0]
        self.assertEqual(embed["title"], "New user signup")
        self.assertEqual(
            embed["description"],
            f"{user.get_display_name()} just created an account.",
        )
        self.assertEqual(embed["url"], f"https://bustimes.org{user.get_absolute_url()}")
        self.assertEqual(embed["fields"][0]["name"], "Email")
        self.assertEqual(embed["fields"][0]["value"], "webhook@example.com")
        self.assertEqual(kwargs["timeout"], 5)

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        NEW_USER_WEBHOOK_URL="https://discord.example/webhook",
    )
    @patch("accounts.notifications.requests.post")
    def test_reactivated_registration_does_not_send_webhook(self, mock_post):
        dummy_uuid = "3d2ef9de-a08b-4504-a657-6dbb1adcf50f"
        password = "arches and avenues"
        Invitation.objects.create(
            uuid=dummy_uuid, expires_at="3000-01-01 00:00:00+00:00"
        )
        User.objects.create(
            username="reactivate@example.com",
            email="reactivate@example.com",
            is_active=False,
        )

        response = self.client.post(
            "/accounts/register/",
            {
                "email": "reactivate@example.com",
                "password1": password,
                "password2": password,
                "invite_code": dummy_uuid,
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        mock_post.assert_not_called()


class UserDirectoryTests(TransactionTestCase):
    def setUp(self):
        self.viewer = User.objects.create_user(
            username="viewer",
            email="viewer@example.com",
            password="secret",
        )
        self.client.force_login(self.viewer)
        self.operator = Operator.objects.create(noc="TEST", name="Test Operator")

    def test_user_list_is_public(self):
        self.client.logout()
        public_user = User.objects.create_user(
            username="public-user",
            email="public@example.com",
            display_name="Public Person",
            password="secret",
        )

        response = self.client.get("/accounts/users/")

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertContains(response, "Users")
        self.assertContains(response, "Public Person")

    def test_user_detail_is_public(self):
        self.client.logout()
        public_user = User.objects.create_user(
            username="public-user-detail",
            email="public-detail@example.com",
            display_name="Public Profile",
            password="secret",
        )

        response = self.client.get(public_user.get_absolute_url())

        self.assertEqual(response.status_code, HTTPStatus.OK)
        self.assertContains(response, "Public Profile")
        self.assertContains(response, "@public-user-detail")
        self.assertNotContains(response, "Edit profile")

    def test_user_liveries_endpoint_uses_the_profile_route(self):
        livery = Livery.objects.create(name="Test Livery", colour="#123456")
        vehicle = Vehicle.objects.create(
            code="LIVERY-1",
            operator=self.operator,
            livery=livery,
        )
        FleetRideLog.objects.create(user=self.viewer, vehicle=vehicle)

        profile_response = self.client.get(self.viewer.get_absolute_url())
        livery_response = self.client.get(
            reverse("user_liveries", args=(self.viewer.pk,))
        )

        self.assertContains(
            profile_response,
            reverse("user_liveries", args=(self.viewer.pk,)),
        )
        self.assertEqual(livery_response.status_code, HTTPStatus.OK)
        self.assertContains(livery_response.json()["html"], "Test Livery")

    def test_user_list_search_filters_results(self):
        target = User.objects.create_user(
            username="target-user",
            email="target@example.com",
            display_name="Target Person",
            password="secret",
        )
        User.objects.create_user(
            username="someone-else",
            email="else@example.com",
            display_name="Another Person",
            password="secret",
        )

        response = self.client.get("/accounts/users/", {"q": "Target"})

        self.assertContains(response, "Target Person")
        self.assertNotContains(response, "Another Person")
        self.assertContains(response, 'name="q"')
        self.assertContains(response, "Top Reviewers")
        self.assertContains(response, "Top Editors")

    def test_user_list_shows_review_and_edit_leaderboards(self):
        top_reviewer = User.objects.create_user(
            username="reviewer",
            email="reviewer@example.com",
            display_name="Best Reviewer",
            password="secret",
        )
        top_editor = User.objects.create_user(
            username="editor",
            email="editor@example.com",
            display_name="Best Editor",
            password="secret",
        )
        vehicle = Vehicle.objects.create(code="1001", operator=self.operator, reg="YX24ABC")

        VehicleReview.objects.create(
            vehicle=vehicle,
            user=top_reviewer,
            rating="5.0",
            message="Excellent",
        )
        VehicleReview.objects.create(
            vehicle=vehicle,
            user=self.viewer,
            rating="4.0",
            message="Good",
        )
        VehicleRevision.objects.create(
            vehicle=vehicle,
            changes={"name": "-\n+Edited"},
            message="Changed the name",
            user=top_editor,
            created_at=timezone.now(),
            pending=False,
            disapproved=False,
        )
        VehicleRevision.objects.create(
            vehicle=vehicle,
            changes={"branding": "-\n+Brand"},
            message="Changed branding",
            user=top_editor,
            created_at=timezone.now(),
            pending=False,
            disapproved=False,
        )

        response = self.client.get("/accounts/users/")

        self.assertContains(response, "Gold")
        self.assertContains(response, "Best Reviewer")
        self.assertContains(response, "Best Editor")

    def test_general_search_includes_users(self):
        searchable_user = User.objects.create_user(
            username="searchable-user",
            email="searchable@example.com",
            display_name="Searchable Person",
            password="secret",
        )

        # Anonymous users should not see user search results
        response = self.client.get("/search", {"q": "Searchable"})
        self.assertNotContains(response, "user")
        self.assertNotContains(response, "Searchable")

        # Authenticated users should see user search results
        self.client.force_login(self.viewer)
        response = self.client.get("/search", {"q": "Searchable"})
        self.assertContains(response, "user")
        self.assertContains(response, "Searchable")

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
        NEW_USER_WEBHOOK_URL="https://discord.example/webhook",
    )
    @patch("accounts.notifications.requests.post")
    def test_failed_registration_does_not_send_webhook(self, mock_post):
        response = self.client.post("/accounts/register/", {})
        self.assertEqual(response.status_code, HTTPStatus.OK)
        mock_post.assert_not_called()

    def test_update_user(self):
        super_user = User.objects.create(
            username="josh", is_staff=True, is_superuser=True, email="j@example.com"
        )
        other_user = User.objects.create(
            username="ken@example.com",
            trusted=None,
            email="ken@example.com",
        )

        # super user sees change link:

        self.client.force_login(super_user)

        response = self.client.get(other_user.get_absolute_url())

        self.assertContains(response, f'"/vehicles/edits?user={other_user.id}"')
        self.assertContains(response, f'"/vehicles/edits?user={other_user.id}&amp;')

        self.assertContains(response, "/change/")

        # set permissions
        response = self.client.post(other_user.get_absolute_url())

        # trust/distrust in admin
        response = self.client.post(
            "/admin/accounts/user/",
            {
                "action": "trust",
                "_selected_action": [other_user.id],
            },
        )
        other_user.refresh_from_db()
        self.assertTrue(other_user.trusted)

        response = self.client.post(
            "/admin/accounts/user/",
            {
                "action": "distrust",
                "_selected_action": [other_user.id],
            },
        )
        other_user.refresh_from_db()
        self.assertFalse(other_user.trusted)

        self.client.force_login(other_user)

        # normal user can't see email addresses
        response = self.client.get(super_user.get_absolute_url())
        self.assertNotContains(response, "ken@example.com")

        # set username:

        response = self.client.post(
            other_user.get_absolute_url(), {"name": "kenton_schweppes"}
        )
        other_user.refresh_from_db()
        self.assertEqual(other_user.username, "kenton_schweppes")

        # try setting a looong username:
        response = self.client.post(
            other_user.get_absolute_url(),
            {"name": "Hubert Blaine Wolfeschlegelsteinhausenbergerdorff Sr."},
        )
        self.assertContains(
            response, ">Ensure this value has at most 50 characters (it has 53).</"
        )

        # try copying someone else's username
        response = self.client.post(other_user.get_absolute_url(), {"name": "josh"})
        self.assertContains(response, ">Username taken<")

        response = self.client.post(
            other_user.get_absolute_url(),
            {
                "username": "kenton_schweppes",
                "display_name": "Kenton",
                "first_name": "Ken",
                "last_name": "Ton",
                "flickr_username": "fleetshots",
                "discord_username": "kenton#1234",
            },
        )
        self.assertContains(response, "This is your profile.")
        other_user.refresh_from_db()
        self.assertEqual(other_user.display_name, "Kenton")
        self.assertEqual(other_user.first_name, "Ken")
        self.assertEqual(other_user.last_name, "Ton")
        self.assertEqual(other_user.flickr_username, "fleetshots")
        self.assertEqual(other_user.discord_username, "kenton#1234")

        self.client.post(other_user.get_absolute_url(), {"name": ""})
        other_user.refresh_from_db()
        self.assertEqual(other_user.username, "ken@example.com")

        # user can delete own account:

        self.client.post(other_user.get_absolute_url(), {"confirm_delete": False})
        # confirm delete not ticked
        other_user.refresh_from_db()
        self.assertTrue(other_user.is_active)

        self.client.post(other_user.get_absolute_url(), {"confirm_delete": "on"})
        other_user.refresh_from_db()
        self.assertFalse(other_user.is_active)

    def test_superuser_can_assign_manual_profile_tags(self):
        super_user = User.objects.create(
            username="admin", is_staff=True, is_superuser=True, email="admin@example.com"
        )
        other_user = User.objects.create(
            username="ken@example.com",
            trusted=None,
            email="ken@example.com",
        )
        tag = ProfileTag.objects.create(name="Editor", slug="editor")

        self.client.force_login(super_user)
        response = self.client.post(
            other_user.get_absolute_url(),
            {"permissions": [], "manual_tags": [tag.id]},
        )

        self.assertEqual(response.status_code, HTTPStatus.OK)
        other_user.refresh_from_db()
        self.assertEqual(list(other_user.manual_tags.all()), [tag])

    @override_settings(
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    )
    def test_registration_without_invite_codes(self):
        registration_settings = RegistrationSettings.get_solo()
        registration_settings.require_invite_codes = False
        registration_settings.save(update_fields=["require_invite_codes"])

        response = self.client.get("/accounts/register/")
        self.assertContains(response, "Invite codes are currently not required")
        self.assertNotContains(response, 'name="invite_code"')
        self.assertContains(response, "Already have an account? Log in")
        self.assertContains(response, '/accounts/login/?next=')

        password = "open top buses forever"
        response = self.client.post(
            "/accounts/register/",
            {
                "email": "noinvite@example.com",
                "password1": password,
                "password2": password,
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.FOUND)
        self.assertEqual(response.url, "/vehicles")

        user = User.objects.get(email="noinvite@example.com")
        self.assertTrue(user.check_password(password))

    def test_admin_can_toggle_invite_code_requirement(self):
        super_user = User.objects.create(
            username="admin", is_staff=True, is_superuser=True, email="admin@example.com"
        )
        self.client.force_login(super_user)

        response = self.client.get("/admin/accounts/invitation/")
        self.assertContains(response, "Require invite codes for registration")

        response = self.client.post(
            "/admin/accounts/invitation/",
            {
                "require_invite_codes": "",
                "_save_registration_settings": "Save",
            },
        )
        self.assertEqual(response.status_code, HTTPStatus.FOUND)

        self.assertFalse(RegistrationSettings.get_solo().require_invite_codes)

    def test_password_reset(self):
        with self.assertNumQueries(0):
            response = self.client.get("/accounts/password_reset/")
        self.assertContains(response, "Reset your password")
        self.assertContains(response, "Email address")

        with self.assertNumQueries(1):
            response = self.client.post(
                "/accounts/password_reset/",
                {
                    "email": "rufus@herring.pizza",
                },
            )
        self.assertEqual(response.url, "/accounts/password_reset/done/")

        with self.assertNumQueries(0):
            response = self.client.get(response.url)
        self.assertContains(
            response,
            "<p>Weâ€™ve emailed you instructions for setting your password, if an account exists with the email you "
            "entered. You should receive them shortly.</p>",
        )
        self.assertEqual([], mail.outbox)
