from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase

from vehicles.views import vehicle_request


class VehicleRequestResponseTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = Mock(is_authenticated=True)
        self.user.has_perm.return_value = True
        self.operator = Mock()

    def call_view(self, request):
        request.user = self.user
        with patch("vehicles.views.get_object_or_404", return_value=self.operator):
            with patch("vehicles.views.render", return_value=HttpResponse()) as render:
                response = vehicle_request(request, "TEST")
                self.assertIsInstance(response, HttpResponse)
                return render.call_args

    def test_get_renders_unbound_request_form(self):
        args = self.call_view(self.factory.get("/operators/TEST/request"))
        self.assertEqual(args.args[1], "edit_vehicle.html")
        self.assertFalse(args.args[2]["form"].is_bound)
        self.assertIs(args.args[2]["object"], self.operator)

    def test_invalid_post_renders_bound_form_with_errors(self):
        args = self.call_view(self.factory.post("/operators/TEST/request", {"summary": "test"}))
        self.assertEqual(args.args[1], "edit_vehicle.html")
        self.assertTrue(args.args[2]["form"].is_bound)
        self.assertIn("fleet_number", args.args[2]["form"].errors)

    def test_user_without_permission_still_sees_rules(self):
        self.user.has_perm.return_value = False
        args = self.call_view(self.factory.get("/operators/TEST/request"))
        self.assertEqual(args.args[1], "rules.html")

    def test_anonymous_request_still_redirects_to_login(self):
        request = self.factory.get("/operators/TEST/request")
        request.user = AnonymousUser()
        response = vehicle_request(request, "TEST")
        self.assertEqual(response.status_code, 302)
