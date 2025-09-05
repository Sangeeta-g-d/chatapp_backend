from django.db import models
from django.conf import settings
from django.utils import timezone
# Create your models here.

class Feed(models.Model):
    FEED_TYPE_CHOICES = [
        ("text", "Text Only"),
        ("file", "File Only"),
        ("both", "File and Text"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feeds"
    )
    feed_type = models.CharField(max_length=10, choices=FEED_TYPE_CHOICES, default="text")
    text = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to="feeds/", blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.email} - {self.feed_type} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        ordering = ["-created_at"]


class FeedLike(models.Model):
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("feed", "user")  # ✅ Prevent multiple likes from same user

    def __str__(self):
        return f"{self.user.email} liked Feed {self.feed.id}"


class FeedComment(models.Model):
    feed = models.ForeignKey(Feed, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    comment = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]  # ✅ Always latest first

    def __str__(self):
        return f"Comment by {self.user.email} on Feed {self.feed.id}"