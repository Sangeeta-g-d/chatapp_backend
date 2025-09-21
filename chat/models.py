from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet
from django.utils import timezone

User = settings.AUTH_USER_MODEL


# ---------- Encryption Utilities ----------
def encrypt_text(text):
    key = settings.ENCRYPTION_KEY.encode()
    fernet = Fernet(key)
    return fernet.encrypt(text.encode()).decode()

def decrypt_text(encrypted):
    key = settings.ENCRYPTION_KEY.encode()
    fernet = Fernet(key)
    return fernet.decrypt(encrypted.encode()).decode()

# ---------- Chat Group (1-1 or Group) ----------
class ChatGroup(models.Model):
    name = models.CharField(max_length=255, blank=True, null=True)
    is_group = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_chats')
    created_at = models.DateTimeField(auto_now_add=True)
    members = models.ManyToManyField(User, related_name='chat_groups')
    group_profile_picture = models.ImageField(upload_to='chat_group_pics/', blank=True, null=True)

    def __str__(self):
        return self.name if self.is_group else f"Chat between {', '.join([u.email for u in self.members.all()])}"

    def get_other_user(self, current_user):
        if not self.is_group:
            return self.members.exclude(id=current_user.id).first()
        return None


class PinnedChat(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pinned_chats')
    chat_group = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name='pinned_by_users')
    pinned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'chat_group')  # Prevent duplicate pins

    def __str__(self):
        return f"{self.user.email} pinned {self.chat_group}"
class Message(models.Model):
    thread = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content_encrypted = models.TextField(blank=True, null=True)
    media = models.FileField(upload_to='chat_media/', blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message from {self.sender.email} in Thread {self.thread.id}"

    def set_content(self, raw_message):
        self.content_encrypted = encrypt_text(raw_message)

    def get_content(self):
        if self.content_encrypted:
            return decrypt_text(self.content_encrypted)
        return None

# ---------- Message Seen Status ----------
class MessageSeenStatus(models.Model):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='seen_statuses')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('message', 'user')


# ---------- Reactions ----------
class MessageReaction(models.Model):
    REACTION_CHOICES = (
        ('like', '👍'),
        ('love', '❤️'),
        ('laugh', '😂'),
        ('sad', '😢'),
        ('angry', '😡'),
    )
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='reactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    reaction = models.CharField(max_length=10, choices=REACTION_CHOICES)
    reacted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')  # One reaction per user per message

    def __str__(self):
        return f"{self.user.email} reacted {self.reaction} on message {self.message.id}"

