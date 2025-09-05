from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class EmailCenter(models.Model):
    email = models.EmailField(unique=True)
    employee_id = models.CharField(max_length=50)
    level = models.CharField(max_length=100)
    
    # Restrictions
    can_add_story = models.BooleanField(default=False)
    can_upload_feed = models.BooleanField(default=False)
    can_share_media = models.BooleanField(default=False)
    can_download_media = models.BooleanField(default=False)

    # Temporary Suspension
    is_suspended = models.BooleanField(default=False)
    suspension_reason = models.CharField(max_length=255, blank=True, null=True)
    suspension_until = models.DateTimeField(blank=True, null=True)  # Optional for timed suspension

    def __str__(self):
        return self.email


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=30)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    level_id = models.ForeignKey(EmailCenter, on_delete=models.CASCADE, null=True)
    dob = models.DateField(null=True, blank=True)
    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    def __str__(self):
        return self.email
    
    def get_full_name(self):
        return self.full_name if self.full_name else self.email

    @property
    def can_add_story(self):
        return self.level_id.can_add_story if self.level_id else False

    @property
    def can_upload_feed(self):
        return self.level_id.can_upload_feed if self.level_id else False

    @property
    def can_share_media(self):
        return self.level_id.can_share_media if self.level_id else False

    @property
    def can_download_media(self):
        return self.level_id.can_download_media if self.level_id else False

    @property
    def is_suspended(self):
        """Check if the user account is temporarily suspended"""
        if not self.level_id:
            return False
        if self.level_id.is_suspended:
            # Optional: check if suspension has expired
            if self.level_id.suspension_until and self.level_id.suspension_until < timezone.now():
                return False
            return True
        return False

class UserProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=15, blank=True,unique=True)
    bio = models.TextField(blank=True)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)

    def __str__(self):
        return f"{self.user.email} Profile"
