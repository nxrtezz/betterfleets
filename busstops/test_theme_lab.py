from django.test import TestCase

from accounts.models import User


class ThemeLabTests(TestCase):
    def test_theme_lab_requires_login(self):
        response = self.client.get("/staff/theme-lab")

        self.assertEqual(response.status_code, 302)

    def test_theme_lab_hides_from_non_staff(self):
        self.client.force_login(User.objects.create(username="member"))

        response = self.client.get("/staff/theme-lab")

        self.assertEqual(response.status_code, 404)

    def test_theme_lab_renders_for_staff(self):
        self.client.force_login(User.objects.create(username="staff", is_staff=True))

        response = self.client.get("/staff/theme-lab")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Theme lab")
        self.assertContains(response, 'id="theme-lab-form"')
        self.assertContains(response, 'id="theme-lab-apply"')
        self.assertContains(response, 'id="theme-suite-existing"')
        self.assertContains(response, 'data-theme-lab-preview="light"')
        self.assertContains(response, 'data-theme-lab-preview="dark"')
        self.assertContains(response, 'id="theme-hex-display"')
        self.assertContains(response, 'id="site-theme-select"')
