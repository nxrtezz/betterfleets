from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import ServiceLog
from .completion import get_user_route_stats

User = get_user_model()


class ServiceLogModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
    
    def test_service_log_creation(self):
        """Test creating a service log."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        log = ServiceLog.objects.create(
            user=self.user,
            service=service,
            ridden=True,
            photographed=False
        )
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.service, service)
        self.assertTrue(log.ridden)
        self.assertFalse(log.photographed)
    
    def test_service_log_unique_constraint(self):
        """Test that duplicate service logs are prevented."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        ServiceLog.objects.create(
            user=self.user,
            service=service,
            ridden=True
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            ServiceLog.objects.create(
                user=self.user,
                service=service,
                ridden=False
            )
    
    def test_service_log_string_representation(self):
        """Test string representation of service logs."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        log = ServiceLog.objects.create(
            user=self.user,
            service=service,
            ridden=True,
            photographed=True
        )
        self.assertIn("ridden", str(log))
        self.assertIn("photographed", str(log))

    def test_route_stats_only_include_ridden_operators(self):
        from busstops.models import Operator, Service

        first_operator = Operator.objects.create(noc="FIRST", name="First Operator")
        second_operator = Operator.objects.create(noc="SECOND", name="Second Operator")
        first_service = Service.objects.create(service_code="FIRST-1", line_name="1")
        second_service = Service.objects.create(service_code="SECOND-1", line_name="1")
        first_service.operator.add(first_operator)
        second_service.operator.add(second_operator)

        self.assertEqual(get_user_route_stats(self.user)["overall_total"], 0)

        ServiceLog.objects.create(user=self.user, service=first_service, ridden=True)

        stats = get_user_route_stats(self.user)
        self.assertEqual(stats["ridden"], 1)
        self.assertEqual(stats["overall_total"], 1)


class ServiceLogViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
        self.client.force_login(self.user)
    
    def test_log_service(self):
        """Test logging a service."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        
        response = self.client.post(reverse('service_logging:log'), {
            'service_id': service.id,
            'ridden': 'true',
            'photographed': 'false'
        })
        
        self.assertEqual(ServiceLog.objects.count(), 1)
        log = ServiceLog.objects.first()
        self.assertTrue(log.ridden)
        self.assertFalse(log.photographed)
    
    def test_log_service_update_existing(self):
        """Test updating an existing service log."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        ServiceLog.objects.create(
            user=self.user,
            service=service,
            ridden=True,
            photographed=False
        )
        
        response = self.client.post(reverse('service_logging:log'), {
            'service_id': service.id,
            'ridden': 'true',
            'photographed': 'true'
        })
        
        log = ServiceLog.objects.first()
        self.assertTrue(log.ridden)
        self.assertTrue(log.photographed)
    
    def test_toggle_service_ridden(self):
        """Test toggling ridden status."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        
        # Toggle on
        response = self.client.post(
            reverse('service_logging:toggle_ridden', args=(service.id,))
        )
        log = ServiceLog.objects.first()
        self.assertTrue(log.ridden)
        
        # Toggle off
        response = self.client.post(
            reverse('service_logging:toggle_ridden', args=(service.id,))
        )
        log.refresh_from_db()
        self.assertFalse(log.ridden)
    
    def test_toggle_service_photographed(self):
        """Test toggling photographed status."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        
        # Toggle on
        response = self.client.post(
            reverse('service_logging:toggle_photographed', args=(service.id,))
        )
        log = ServiceLog.objects.first()
        self.assertTrue(log.photographed)
        
        # Toggle off
        response = self.client.post(
            reverse('service_logging:toggle_photographed', args=(service.id,))
        )
        log.refresh_from_db()
        self.assertFalse(log.photographed)
    
    def test_log_service_ajax(self):
        """Test logging a service via AJAX."""
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        
        response = self.client.post(reverse('service_logging:log'), {
            'service_id': service.id,
            'ridden': 'true',
            'photographed': 'false'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
        self.assertTrue(response.json()['ridden'])
    
    def test_authentication_required(self):
        """Test that authentication is required."""
        self.client.logout()
        
        from busstops.models import Service
        service = Service.objects.create(
            service_code="TEST",
            line_name="Test Service"
        )
        
        response = self.client.post(reverse('service_logging:log'), {
            'service_id': service.id,
            'ridden': 'true',
            'photographed': 'false'
        })
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
