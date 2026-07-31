from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class ServiceLog(models.Model):
    """
    Track which services a user has logged (ridden/photographed).
    """
    user = models.ForeignKey(User, models.CASCADE, related_name="service_logs")
    service = models.ForeignKey(
        "busstops.Service",
        models.CASCADE,
        related_name="service_logs"
    )
    ridden = models.BooleanField(default=False, help_text="User has ridden this service")
    photographed = models.BooleanField(default=False, help_text="User has photographed this service")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, help_text="Optional notes about this service")
    
    class Meta:
        ordering = ("-updated_at",)
        verbose_name = "service log"
        verbose_name_plural = "service logs"
        unique_together = ("user", "service")
        indexes = [
            models.Index(fields=["user", "service"]),
            models.Index(fields=["service", "ridden"]),
            models.Index(fields=["service", "photographed"]),
        ]
    
    def __str__(self):
        status_parts = []
        if self.ridden:
            status_parts.append("ridden")
        if self.photographed:
            status_parts.append("photographed")
        
        status = " and ".join(status_parts) if status_parts else "logged"
        return f"{self.user} - {self.service} ({status})"
