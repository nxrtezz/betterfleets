import logging
from django.db import models
from django.db.models import QuerySet

logger = logging.getLogger(__name__)


class SafeQuerySet(QuerySet):
    """
    A QuerySet wrapper that handles UnicodeDecodeError exceptions gracefully.
    """
    
    def __iter__(self):
        try:
            return super().__iter__()
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError in SafeQuerySet.__iter__: {e}")
            # Return empty iterator
            return iter([])
    
    def __getitem__(self, key):
        try:
            return super().__getitem__(key)
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError in SafeQuerySet.__getitem__: {e}")
            # Return empty queryset
            return self.none()
    
    def count(self):
        try:
            return super().count()
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError in SafeQuerySet.count: {e}")
            return 0


class SafeManager(models.Manager):
    """
    A model manager that uses SafeQuerySet to handle encoding errors.
    """
    
    def get_queryset(self):
        return SafeQuerySet(self.model, using=self._db)
    
    def safe_all(self):
        """Get all objects safely, handling encoding errors"""
        try:
            return self.get_queryset()
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError in safe_all: {e}")
            return self.none()
    
    def safe_filter(self, *args, **kwargs):
        """Filter objects safely, handling encoding errors"""
        try:
            return self.get_queryset().filter(*args, **kwargs)
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError in safe_filter: {e}")
            return self.none()
