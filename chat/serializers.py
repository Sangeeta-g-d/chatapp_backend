# serializers.py
from rest_framework import serializers
from admin_part.models import CustomUser, UserProfile
from .models import *
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils.timezone import localtime
import pytz
from auth_api.models import UserDevice
User = get_user_model()


class CustomUserWithOptionalProfileSerializer(serializers.ModelSerializer):
    bio = serializers.SerializerMethodField()
    profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ['id', 'full_name', 'bio', 'profile_picture']

    def get_bio(self, obj):
        try:
            return obj.userprofile.bio
        except UserProfile.DoesNotExist:
            return None

    def get_profile_picture(self, obj):
        request = self.context.get('request')
        try:
            profile_picture = obj.userprofile.profile_picture
            if profile_picture and hasattr(profile_picture, 'url'):
                return request.build_absolute_uri(profile_picture.url)
        except UserProfile.DoesNotExist:
            pass
        return None

class GroupChatCreateSerializer(serializers.ModelSerializer):
    members = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), many=True)
    group_profile_picture = serializers.ImageField(required=False, allow_null=True)

    class Meta:
        model = ChatGroup
        fields = ['name', 'members', 'group_profile_picture']

    def validate(self, data):
        if len(data['members']) < 2:
            raise serializers.ValidationError("Group must have at least 2 members.")
        return data

    def create(self, validated_data):
        members = validated_data.pop('members')
        created_by = self.context['request'].user
        group = ChatGroup.objects.create(created_by=created_by, is_group=True, **validated_data)
        group.members.set(members + [created_by])  # Include creator by default
        return group


class MessageSeenStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageSeenStatus
        fields = ['message', 'user', 'seen_at']
        read_only_fields = ['seen_at']

    def create(self, validated_data):
        # Avoid duplicate entry due to unique_together
        obj, created = MessageSeenStatus.objects.get_or_create(**validated_data)
        return obj
    

class MessageReactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MessageReaction
        fields = ['message', 'user', 'reaction']

    def create(self, validated_data):
        # If user already reacted, update it
        obj, created = MessageReaction.objects.update_or_create(
            message=validated_data['message'],
            user=validated_data['user'],
            defaults={'reaction': validated_data['reaction']}
        )
        return obj


class GroupMemberSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    bio = serializers.CharField(source="userprofile.bio", read_only=True)
    profile_picture = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()

    class Meta:
        model = CustomUser
        fields = ["id", "full_name", "email", "bio", "profile_picture","is_admin"]

    def get_full_name(self, obj):
        request = self.context.get("request")
        if request and obj.id == request.user.id:  # ✅ If current user
            return "You"
        return obj.get_full_name()

    def get_profile_picture(self, obj):
        request = self.context.get("request")
        if hasattr(obj, "userprofile") and obj.userprofile.profile_picture:
            return request.build_absolute_uri(obj.userprofile.profile_picture.url)
        return None
    def get_is_admin(self, obj):
        group = self.context.get("group")
        return group and obj.id == group.created_by_id


class ChatGroupSerializer(serializers.ModelSerializer):
    members = serializers.SerializerMethodField()
    group_profile_picture = serializers.SerializerMethodField()

    class Meta:
        model = ChatGroup
        fields = ["id", "name", "group_profile_picture", "members"]

    def get_group_profile_picture(self, obj):
        request = self.context.get("request")
        if obj.group_profile_picture:
            return request.build_absolute_uri(obj.group_profile_picture.url)
        return None

    def get_members(self, obj):
        request = self.context.get("request")
        members = list(obj.members.all())
    
        # ✅ Sort so logged‑in user comes first
        members.sort(key=lambda m: 0 if m.id == request.user.id else 1)
    
        # ✅ Pass group into context
        return GroupMemberSerializer(
            members,
            many=True,
            context={"request": request, "group": obj}
        ).data
    
# class MessageSerializer(serializers.ModelSerializer):
#     content = serializers.SerializerMethodField()
#     media_url = serializers.SerializerMethodField()

#     class Meta:
#         model = Message
#         fields = ['id', 'sender', 'content', 'media_url', 'timestamp']

#     def get_content(self, obj):
#         return obj.get_content()

#     def get_media_url(self, obj):
#         return obj.media.url if obj.media else None

class MessageSerializer(serializers.ModelSerializer):
    # We expose "message" as a plain text field for input/output
    message = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = Message
        fields = ['id', 'thread', 'sender', 'message', 'media', 'timestamp']
        read_only_fields = ['id', 'timestamp']

    def create(self, validated_data):
        message_text = validated_data.pop('message', None)
        msg = Message(**validated_data)
        if message_text:
            msg.set_content(message_text)  # stored encrypted
        msg.save()
        return msg

    def to_representation(self, instance):
        request = self.context.get("request", None)  # ✅ safe lookup
        saudi_tz = pytz.timezone("Asia/Riyadh")

        media_url = None
        if instance.media:
            if request:
                media_url = request.build_absolute_uri(instance.media.url)
            else:
                # fallback to relative URL
                media_url = instance.media.url

        return {
            "id": instance.id,
            "thread": instance.thread.id,
            "sender": instance.sender.id,
            "message": instance.get_content(),  # decrypted text (or None)
            "media_url": media_url,
            "timestamp": localtime(instance.timestamp, saudi_tz).strftime("%Y-%m-%d %H:%M:%S"),  # ✅ Saudi time
        }

