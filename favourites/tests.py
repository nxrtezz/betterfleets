from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.exceptions import ValidationError
from .models import Favourite, FavouriteType, MAX_FAVOURITES

User = get_user_model()


class FavouriteModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
    
    def test_favourite_creation(self):
        """Test creating a favourite."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        favourite = Favourite.objects.create(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=operator
        )
        self.assertEqual(favourite.user, self.user)
        self.assertEqual(favourite.operator, operator)
    
    def test_favourite_unique_constraint(self):
        """Test that duplicate favourites are prevented."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        Favourite.objects.create(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=operator
        )
        
        with self.assertRaises(Exception):  # IntegrityError
            Favourite.objects.create(
                user=self.user,
                favourite_type=FavouriteType.OPERATOR,
                operator=operator
            )
    
    def test_favourite_validation_operator(self):
        """Test validation for operator favourites."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        
        # Valid operator favourite
        favourite = Favourite(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=operator
        )
        favourite.full_clean()  # Should not raise
        
        # Invalid - missing operator
        favourite = Favourite(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR
        )
        with self.assertRaises(ValidationError):
            favourite.full_clean()
    
    def test_favourite_max_limit(self):
        """Test that max favourites limit is enforced."""
        from busstops.models import Operator
        
        # Create MAX_FAVOURITES operators
        for i in range(MAX_FAVOURITES):
            Operator.objects.create(
                noc=f"TEST{i}",
                name=f"Test Operator {i}"
            )
        
        operators = list(Operator.objects.all())
        
        # Add MAX_FAVOURITES favourites
        for operator in operators:
            Favourite.objects.create(
                user=self.user,
                favourite_type=FavouriteType.OPERATOR,
                operator=operator
            )
        
        # Try to add one more - should fail
        new_operator = Operator.objects.create(
            noc="TESTX",
            name="Test Operator X"
        )
        favourite = Favourite(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=new_operator
        )
        with self.assertRaises(ValidationError):
            favourite.full_clean()
    
    def test_favourite_string_representation(self):
        """Test string representation of favourites."""
        from busstops.models import Operator, Vehicle, Service
        
        operator = Operator.objects.create(noc="TEST", name="Test Operator")
        favourite = Favourite.objects.create(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=operator
        )
        self.assertIn("Test Operator", str(favourite))


class FavouriteViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email="test@example.com",
            username="testuser"
        )
        self.client.force_login(self.user)
    
    def test_add_favourite(self):
        """Test adding a favourite via POST."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        
        response = self.client.post(reverse('favourites:add'), {
            'type': FavouriteType.OPERATOR,
            'operator_id': operator.id
        })
        
        self.assertEqual(Favourite.objects.count(), 1)
        self.assertEqual(Favourite.objects.first().operator, operator)
    
    def test_remove_favourite(self):
        """Test removing a favourite."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        favourite = Favourite.objects.create(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=operator
        )
        
        response = self.client.post(reverse('favourites:remove', args=(favourite.id,)))
        
        self.assertEqual(Favourite.objects.count(), 0)
    
    def test_toggle_favourite_add(self):
        """Test toggling a favourite (add)."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        
        response = self.client.post(reverse('favourites:toggle'), {
            'type': FavouriteType.OPERATOR,
            'operator_id': operator.id
        })
        
        self.assertEqual(Favourite.objects.count(), 1)
    
    def test_toggle_favourite_remove(self):
        """Test toggling a favourite (remove)."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        Favourite.objects.create(
            user=self.user,
            favourite_type=FavouriteType.OPERATOR,
            operator=operator
        )
        
        response = self.client.post(reverse('favourites:toggle'), {
            'type': FavouriteType.OPERATOR,
            'operator_id': operator.id
        })
        
        self.assertEqual(Favourite.objects.count(), 0)
    
    def test_add_favourite_ajax(self):
        """Test adding a favourite via AJAX."""
        from busstops.models import Operator
        operator = Operator.objects.create(
            noc="TEST",
            name="Test Operator"
        )
        
        response = self.client.post(reverse('favourites:add'), {
            'type': FavouriteType.OPERATOR,
            'operator_id': operator.id
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['success'], True)
