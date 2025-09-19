from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from .models import *
from .serializers import *
from django.utils import timezone
from datetime import timedelta

class UploadStoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        serializer = StorySerializer(data=request.data)
        if serializer.is_valid():
            story = serializer.save(user=user, expires_at=timezone.now() + timedelta(hours=24))
            return Response(StorySerializer(story, context={'request': request}).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class StoryListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user and user.is_authenticated and user.is_suspended:
            return Response(
                {
                    "status": 403,
                    "message": "Your account is suspended.",
                    "data": {
                        "suspension_reason": getattr(user.level_id, "suspension_reason", None),
                        "suspension_until": getattr(user.level_id, "suspension_until", None),
                    },
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        now = timezone.now()
        base_url = request.build_absolute_uri('/')[:-1]
        user = request.user

        # Get all valid stories
        all_stories = StoryModel.objects.filter(expires_at__gt=now).select_related('user', 'user__userprofile')

        # Get viewed story IDs for current user
        viewed_story_ids = set(StoryView.objects.filter(user=user).values_list('story_id', flat=True))

        context = {
            "base_url": base_url,
            "viewed_story_ids": viewed_story_ids,
            "show_viewers": False
        }

        # Separate stories into my stories and others'
        my_stories_group = defaultdict(list)
        other_stories_group = defaultdict(list)

        for story in all_stories:
            if story.user.id == user.id:
                my_stories_group[story.user.id].append(story)
            else:
                other_stories_group[story.user.id].append(story)

        def serialize_group(group_dict):
            grouped_serialized = []
            for user_id, stories in group_dict.items():
                user_obj = stories[0].user
                story_serializer = StoryListSerializer(stories, many=True, context=context)
                grouped_serialized.append({
                    
                    "user_id": user_obj.id,
                    "username": user_obj.get_full_name(),
                    "profile_picture": (
                        f"{base_url}{user_obj.userprofile.profile_picture.url}"
                        if hasattr(user_obj, 'userprofile') and user_obj.userprofile.profile_picture
                        else None
                    ),
                    "stories": story_serializer.data
                })
            return grouped_serialized

        return Response({
            "user_level": user.level_id.level if user.level_id else None,
            "can_upload":user.can_add_story,
            "my_stories": serialize_group(my_stories_group),
            "other_user_stories": serialize_group(other_stories_group)
        }, status=status.HTTP_200_OK)



class StoryViewRecordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, story_id):
        user = request.user
        try:
            story = StoryModel.objects.get(id=story_id)
        except StoryModel.DoesNotExist:
            return Response({"error": "Story not found"}, status=404)

        StoryView.objects.get_or_create(user=user, story=story)
        return Response({"message": "Story view recorded"}, status=200)


class DeleteStoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, story_id):
        story = get_object_or_404(StoryModel, id=story_id)

        # ✅ Ensure only the owner can delete
        if story.user != request.user:
            return Response(
                {"error": "You are not allowed to delete this story."},
                status=status.HTTP_403_FORBIDDEN
            )

        story.delete()
        return Response(
            {"message": "Story deleted successfully."},
            status=status.HTTP_200_OK
        )