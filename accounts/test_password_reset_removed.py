from django.test import SimpleTestCase
from django.urls import Resolver404, resolve, reverse


class RemovedPasswordResetTests(SimpleTestCase):
    def test_reset_routes_are_not_exposed(self):
        for path in ["/accounts/password_reset/", "/accounts/password_reset/done/", "/accounts/reset/user/token/", "/accounts/reset/done/"]:
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)

    def test_login_no_longer_offers_reset(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Lost password?")
        self.assertNotContains(response, "/accounts/password_reset/")

    def test_password_change_route_remains(self):
        self.assertEqual(resolve("/accounts/password_change/").url_name, "password_change")
