from rest_framework import serializers
from .models import StoryModel
from django.utils.timezone import localtime
from collections import defaultdict
import pytz
from pytz import timezone as pytz_timezone
IST = pytz_timezone("Asia/Kolkata")

class StorySerializer(serializers.ModelSerializer):
    media_url = serializers.SerializerMethodField()
    created_at_ist = serializers.SerializerMethodField()
    expires_at_ist = serializers.SerializerMethodField()

    class Meta:
        model = StoryModel
        fields = ['id', 'content_text', 'media', 'media_url', 'created_at_ist', 'expires_at_ist']
        read_only_fields = ['created_at_ist', 'expires_at_ist']

    def get_media_url(self, obj):
        request = self.context.get('request')
        if obj.media and hasattr(obj.media, 'url') and request:
            return request.build_absolute_uri(obj.media.url)
        return None

    def get_created_at_ist(self, obj):
        ist = pytz.timezone("Asia/Kolkata")
        return localtime(obj.created_at, timezone=ist).strftime('%Y-%m-%d %H:%M:%S')

    def get_expires_at_ist(self, obj):
        ist = pytz.timezone("Asia/Kolkata")
        return localtime(obj.expires_at, timezone=ist).strftime('%Y-%m-%d %H:%M:%S')





class StoryListSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()
    media_url = serializers.SerializerMethodField()
    created_at_ist = serializers.SerializerMethodField()
    expires_at_ist = serializers.SerializerMethodField()
    has_viewed = serializers.SerializerMethodField()
    view_count = serializers.SerializerMethodField()
    viewers = serializers.SerializerMethodField()

    class Meta:
        model = StoryModel
        fields = [
            'id', 'content_text', 'media_url',
            'created_at_ist', 'expires_at_ist',
            'username', 'profile_picture', 'has_viewed',
            'view_count', 'viewers'
        ]

    def get_username(self, obj):
        return obj.user.get_full_name()

    def get_profile_picture(self, obj):
        request = self.context.get("base_url")
        if hasattr(obj.user, 'userprofile') and obj.user.userprofile.profile_picture:
            return f"{request}{obj.user.userprofile.profile_picture.url}"
        return None

    def get_media_url(self, obj):
        request = self.context.get("base_url")
        if obj.media:
            return f"{request}{obj.media.url}"
        return None

    def get_created_at_ist(self, obj):
        return obj.created_at.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

    def get_expires_at_ist(self, obj):
        return obj.expires_at.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')

    def get_has_viewed(self, obj):
        viewed_story_ids = self.context.get("viewed_story_ids", set())
        return obj.id in viewed_story_ids

    def get_view_count(self, obj):
        return obj.views.count()

    def get_viewers(self, obj):
        if not self.context.get("show_viewers"):
            return []  # Or return None if preferred

        request = self.context.get("base_url")
        viewers = obj.views.select_related('user', 'user__userprofile').all()
        return [
            {
                "user_id": v.user.id,
                "full_name": v.user.get_full_name(),
                "profile_picture": (
                    f"{request}{v.user.userprofile.profile_picture.url}"
                    if hasattr(v.user, 'userprofile') and v.user.userprofile.profile_picture
                    else None
                ),
                "viewed_at_ist": v.viewed_at.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S')
            }
            for v in viewers
        ]

class GroupedStorySerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    username = serializers.CharField()
    profile_picture = serializers.CharField(allow_null=True)
    stories = StoryListSerializer(many=True)