# signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from admin_part.models import CustomUser
from .models import UserStatus


@receiver(post_save, sender=CustomUser)
def create_status(sender, instance, created, **kwargs):
    if created:
        UserStatus.objects.create(user=instance)
