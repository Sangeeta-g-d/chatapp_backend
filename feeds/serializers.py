from rest_framework import serializers
from .models import *
import pytz

class FeedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feed
        fields = ["id", "feed_type", "text", "file", "created_at"]
        read_only_fields = ["id", "created_at", "feed_type"]

    def create(self, validated_data):
        request = self.context.get("request")
        text = validated_data.get("text")
        file = validated_data.get("file")

        # ✅ Decide feed type automatically
        if text and file:
            validated_data["feed_type"] = "both"
        elif text:
            validated_data["feed_type"] = "text"
        elif file:
            validated_data["feed_type"] = "file"
        else:
            raise serializers.ValidationError("Feed must have either text, file, or both.")

        validated_data["user"] = request.user
        return super().create(validated_data)


class FeedLikeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FeedLike
        fields = ["id", "feed", "user", "created_at"]
        read_only_fields = ["id", "user", "created_at"]

class FeedCommentSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = FeedComment
        fields = ["id", "feed", "user", "user_name", "user_email", "comment", "created_at"]
        read_only_fields = ["id", "user", "user_name", "user_email", "created_at", "feed"]

class FeedListSerializer(serializers.ModelSerializer):
    like_count = serializers.IntegerField(source="likes.count", read_only=True)
    comment_count = serializers.IntegerField(source="comments.count", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)
    profile_picture = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()

    class Meta:
        model = Feed
        fields = [
            "id",
            "user_name",
            "profile_picture",
            "feed_type",
            "text",
            "file",
            "created_at",
            "like_count",
            "comment_count",
            "is_liked",
        ]

    def get_created_at(self, obj):
        saudi_tz = pytz.timezone("Asia/Riyadh")  # ✅ Saudi timezone
        local_time = timezone.localtime(obj.created_at, saudi_tz)
        # ✅ ISO 8601 format with microseconds + Z (Zulu/UTC-like suffix)
        return local_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def get_profile_picture(self, obj):
        request = self.context.get("request")
        if hasattr(obj.user, "userprofile") and obj.user.userprofile.profile_picture:
            return request.build_absolute_uri(obj.user.userprofile.profile_picture.url)
        return None

    def get_is_liked(self, obj):
        request = self.context.get("request")
        user = request.user if request else None
        if user and user.is_authenticated:
            return obj.likes.filter(user=user).exists()
        return False

class FeedCommentsSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.full_name", read_only=True)  # optional extra field
    user_email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = FeedComment
        fields = ["id", "feed", "user", "user_name", "user_email", "comment", "created_at"]

    def get_user_profile(self, obj):
        request = self.context.get("request")
        if obj.user.profile_image:
            return request.build_absolute_uri(obj.user.profile_image.url)
        return None