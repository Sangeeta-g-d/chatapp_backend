from django.db import models
from django.utils import timezone
import datetime
from admin_part.models import CustomUser
# Create your models here.
class EmailOTP(models.Model):
    email = models.EmailField()
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def is_expired(self):
        return timezone.now() > self.created_at + datetime.timedelta(minutes=10)

    def __str__(self):
        return f"{self.email} - {self.otp}"
    

class UserDevice(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name="devices")
    device_token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)