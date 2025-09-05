from django.db import models
from django.utils import timezone
from datetime import timedelta
from admin_part.models import CustomUser

class StoryModel(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='stories')
    content_text = models.TextField(blank=True, null=True)
    media = models.FileField(upload_to='story_media/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    def save(self, *args, **kwargs):
        # Auto set expires_at to 24 hours from now if not provided
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)

    def is_expired(self):
        return timezone.now() >= self.expires_at

    def __str__(self):
        return f"Story by {self.user.email} at {self.created_at}"

class StoryView(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='viewed_stories')
    story = models.ForeignKey(StoryModel, on_delete=models.CASCADE, related_name='views')
    viewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'story')  # Prevent duplicate views

    def __str__(self):
        return f"{self.user.email} viewed story {self.story.id}"