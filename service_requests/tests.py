from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import Request, RequestComment, RequestHistory, RequestCategory, RequestStatus

User = get_user_model()


class RequestModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
    
    def test_request_creation(self):
        """Test creating a basic request."""
        request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
        self.assertEqual(request.title, "Test Request")
        self.assertEqual(request.status, RequestStatus.OPEN)
        self.assertEqual(request.author, self.user)
    
    def test_request_status_change(self):
        """Test changing request status auto-updates resolved_at."""
        request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
        self.assertIsNone(request.resolved_at)
        
        request.status = RequestStatus.RESOLVED
        request.resolved_by = self.user
        request.save()
        
        self.assertIsNotNone(request.resolved_at)
    
    def test_request_category_validation(self):
        """Test category-specific validation."""
        from .forms import RequestForm
        from vehicles.models import Vehicle, VehicleType, Livery
        from busstops.models import Operator, Service
        
        # Test vehicle request without vehicle or fleet number/registration
        form = RequestForm(data={
            'title': 'Vehicle Request',
            'description': 'Test',
            'category': RequestCategory.VEHICLE
        })
        self.assertFalse(form.is_valid())
        self.assertIn('Vehicle requests must specify', str(form.errors))


class RequestViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
        self.client.force_login(self.user)
    
    def test_request_list_view(self):
        """Test request list page."""
        response = self.client.get(reverse('requests:list'))
        self.assertEqual(response.status_code, 200)
    
    def test_request_create_view(self):
        """Test creating a request."""
        response = self.client.post(reverse('requests:create'), {
            'title': 'New Request',
            'description': 'Test description',
            'category': RequestCategory.OTHER
        })
        self.assertEqual(Request.objects.count(), 1)
        self.assertEqual(Request.objects.first().title, 'New Request')
    
    def test_request_detail_view(self):
        """Test viewing a request detail."""
        request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
        response = self.client.get(reverse('requests:detail', args=(request.id,)))
        self.assertEqual(response.status_code, 200)
    
    def test_add_comment(self):
        """Test adding a comment to a request."""
        request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
        response = self.client.post(reverse('requests:add_comment', args=(request.id,)), {
            'content': 'Test comment'
        })
        self.assertEqual(RequestComment.objects.count(), 1)
    
    def test_change_status_staff_only(self):
        """Test that only staff can change request status."""
        request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
        response = self.client.post(reverse('requests:change_status', args=(request.id,)), {
            'status': RequestStatus.RESOLVED
        })
        # Non-staff user should be redirected or denied
        self.assertNotEqual(response.status_code, 200)
    
    def test_request_update_by_author(self):
        """Test that request author can update their request."""
        request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
        response = self.client.post(reverse('requests:update', args=(request.id,)), {
            'title': 'Updated Title',
            'description': 'Updated description',
            'category': RequestCategory.OTHER
        })
        request.refresh_from_db()
        self.assertEqual(request.title, 'Updated Title')


class RequestCommentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
        self.request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
    
    def test_comment_creation(self):
        """Test creating a comment."""
        comment = RequestComment.objects.create(
            request=self.request,
            author=self.user,
            content="Test comment"
        )
        self.assertEqual(comment.content, "Test comment")
        self.assertEqual(comment.request, self.request)


class RequestHistoryModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
        self.request = Request.objects.create(
            title="Test Request",
            description="Test description",
            category=RequestCategory.OTHER,
            author=self.user
        )
    
    def test_history_creation(self):
        """Test creating a history entry."""
        history = RequestHistory.objects.create(
            request=self.request,
            user=self.user,
            action="created",
            description="Request created"
        )
        self.assertEqual(history.action, "created")
        self.assertEqual(history.request, self.request)
