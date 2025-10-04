from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import *
from rest_framework import generics
from .serializers import *

class CreateFeedAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if request.user.is_suspended:
            return Response(
                {
                    "status": 403,
                    "message": "Your account is suspended.",
                    "data": {
                        "suspension_reason": getattr(request.user.level_id, "suspension_reason", None),
                        "suspension_until": getattr(request.user.level_id, "suspension_until", None),
                    },
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = FeedSerializer(data=request.data, context={"request": request})
        if serializer.is_valid():
            feed = serializer.save()
            return Response(
                {
                    "message": "Feed uploaded successfully",
                    "feed": FeedSerializer(feed).data
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ToggleFeedLikeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, feed_id, *args, **kwargs):
        user = request.user
        if user.is_suspended:
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
        try:
            feed = Feed.objects.get(id=feed_id)
        except Feed.DoesNotExist:
            return Response({"error": "Feed not found"}, status=status.HTTP_404_NOT_FOUND)

        like, created = FeedLike.objects.get_or_create(feed=feed, user=request.user)

        if not created:
            # Already liked → remove it
            like.delete()
            return Response({"message": "Like removed successfully ❌"}, status=status.HTTP_200_OK)

        return Response({"message": "Feed liked successfully ❤️"}, status=status.HTTP_201_CREATED)
    

class AddFeedCommentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, feed_id, *args, **kwargs):
        user = request.user
        if user.is_suspended:
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
        try:
            feed = Feed.objects.get(id=feed_id)
        except Feed.DoesNotExist:
            return Response({"error": "Feed not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = FeedCommentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user, feed=feed)
            return Response(
                {"message": "Comment added successfully 💬", "comment": serializer.data},
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class FeedListAPIView(APIView):
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

        feeds = Feed.objects.all().order_by("-created_at")  # ✅ latest first
        serializer = FeedListSerializer(feeds, many=True, context={"request": request})

        # ✅ Logged-in user details
        user_level = user.level_id.level if user.level_id else None
        user_role = user.role if hasattr(user, "role") else None  # ✅ Add role

        return Response({
            "user_level": user_level,      
            "user_role": user_role,          
            "can_upload": user.can_upload_feed,  
            "feeds": serializer.data
        })

class FeedCommentsListAPIView(generics.ListAPIView):
    serializer_class = FeedCommentsSerializer
    permission_classes = [IsAuthenticated]  # remove if not needed

    def get_queryset(self):
        feed_id = self.kwargs["feed_id"]
        return FeedComment.objects.filter(feed_id=feed_id).order_by("-created_at")  


class FeedFilterAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_role = user.role

        # 🔹 Optional filter by query param (e.g., ?role=Employee)
        role_filter = request.query_params.get("role")

        feeds = Feed.objects.all().order_by("-created_at")

        if role_filter:
            # Client explicitly requested a role filter
            feeds = feeds.filter(user__role=role_filter)
        else:
            # Default: filter by logged-in user role
            feeds = feeds.filter(user__role=user_role)

        serializer = FeedListSerializer(feeds, many=True, context={"request": request})

        return Response({
            "applied_role": role_filter if role_filter else user_role,  # ✅ Show what role was used
            "feeds": serializer.data
        })