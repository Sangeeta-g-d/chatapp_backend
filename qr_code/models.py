# models.py
import uuid
from django.db import models
from django.utils import timezone
from django.conf import settings

class QRSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    approved_at = models.DateTimeField(null=True, blank=True)
    # Optional: store extra client info (IP, user-agent)
    web_client_info = models.JSONField(blank=True, null=True)

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def mark_approved(self, user):
        self.approved = True
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save()
