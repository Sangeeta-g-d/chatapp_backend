# views.py
from rest_framework.views import APIView
from django.shortcuts import render
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from admin_part.models import UserProfile
from rest_framework import status
from django.db.models import Max
from django.shortcuts import get_object_or_404
from .serializers import *
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .utils import send_ws_event
from . models import *
from rest_framework.decorators import api_view, permission_classes
from django.contrib.auth import get_user_model

User = get_user_model()   # ✅ This ensures User is the actual model, not a string

def chat_ui_view(request):
    return render(request, 'chat_g.html')

class OtherUsersProfileAPIView(APIView):
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
        users = CustomUser.objects.exclude(id=request.user.id).exclude(is_superuser=True)
        serializer = CustomUserWithOptionalProfileSerializer(users, many=True, context={'request': request})
        return Response(serializer.data)

class ChatHistoryAPIView(APIView):
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
        current_user = request.user
        user_id = request.query_params.get('user_id')  # for 1-1 chat
        chat_group_id = request.query_params.get('chat_group_id')  # for group chat

        # Validate input
        if not user_id and not chat_group_id:
            return Response({"detail": "Provide either 'user_id' or 'chat_group_id'."}, status=400)

        # 1-on-1 chat logic
        if user_id:
            try:
                receiver = CustomUser.objects.get(id=user_id)
            except CustomUser.DoesNotExist:
                return Response({"detail": "Target user not found."}, status=404)

            chat_group = ChatGroup.objects.filter(
                is_group=False,
                members=current_user
            ).filter(members=receiver).distinct().first()

            if not chat_group:
                chat_group = ChatGroup.objects.create(is_group=False, created_by=current_user)
                chat_group.members.add(current_user, receiver)

        # Group chat logic
        elif chat_group_id:
            try:
                chat_group = ChatGroup.objects.get(id=chat_group_id, is_group=True)
            except ChatGroup.DoesNotExist:
                return Response({"detail": "Group chat not found."}, status=404)

            if current_user not in chat_group.members.all():
                return Response({"detail": "You are not a member of this group."}, status=403)

            receiver = None  # not needed for group chat

        # Fetch messages
        messages = Message.objects.filter(
            thread=chat_group
        ).prefetch_related(
            'seen_statuses',
            # 'reactions',  # 🚫 Commented out
            'sender'
        ).order_by('timestamp')

        messages_data = []
        for msg in messages:
            seen_data = [{
                "user_id": seen.user.id,
                "seen_at": seen.seen_at
            } for seen in msg.seen_statuses.all()]

            # 🚫 Reactions temporarily disabled
            # reaction_data = [{
            #     "user_id": r.user.id,
            #     "reaction": r.reaction,
            #     "emoji": dict(MessageReaction.REACTION_CHOICES).get(r.reaction, ''),
            #     "reacted_at": r.reacted_at
            # } for r in msg.reactions.all()]

            messages_data.append({
                "id": msg.id,
                "sender_id": msg.sender.id,
                "sender_name": msg.sender.full_name,
                "message": msg.get_content(),
                "media": request.build_absolute_uri(msg.media.url) if msg.media else None,
                "timestamp": msg.timestamp,
                "seen_status": seen_data,
                # "reactions": reaction_data,  # 🚫 Commented out
                "is_seen": msg.seen_statuses.filter(user=current_user).exists(),
                # "my_reaction": next((r for r in reaction_data if r['user_id'] == current_user.id), None),  # 🚫 Commented out
            })

        group_profile_url = (
            request.build_absolute_uri(chat_group.group_profile_picture.url)
            if chat_group.group_profile_picture
            else None
        )

        response_data = {
            "chat_group_id": chat_group.id,
            "can_share_media":current_user.can_share_media,
            "is_group": chat_group.is_group,
            "group_name": chat_group.name if chat_group.is_group else None,
            "group_image": group_profile_url,
            "current_user_id": current_user.id,
            "receiver": {
                "id": receiver.id,
                "full_name": receiver.full_name,
                "email": receiver.email,
                "profile_image": (
                    request.build_absolute_uri(receiver.userprofile.profile_picture.url)
                    if hasattr(receiver, 'userprofile') and receiver.userprofile.profile_picture
                    else None
                )
            } if receiver else None,
            "messages": messages_data,
        }

        return Response(response_data, status=status.HTTP_200_OK)

    

class CreateGroupChatAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GroupChatCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            group = serializer.save()
            return Response({
                "message": "Group chat created successfully.",
                "group_id": group.id,
                "name": group.name,
                "members": [user.id for user in group.members.all()],
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    



@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_message_seen(request):
    message_id = request.data.get("message_id")
    try:
        message = Message.objects.get(id=message_id)
        # Create or update the seen status
        seen_status, created = MessageSeenStatus.objects.get_or_create(
            message=message,
            user=request.user,
            defaults={'seen_at': timezone.now()}
        )
        
        if not created:
            seen_status.seen_at = timezone.now()
            seen_status.save()

        # Prepare data for WebSocket
        seen_data = {
            'user_id': request.user.id,
            'seen_at': str(seen_status.seen_at)
        }

        # Send real-time seen update to WebSocket group
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{message.thread.id}",
            {
                "type": "seen.update",
                "message_id": message.id,
                "seen": [seen_data],
            }
        )

        return Response({"success": True, "seen_at": seen_status.seen_at})
    except Message.DoesNotExist:
        return Response({"error": "Message not found"}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def add_reaction_to_message(request):
    message_id = request.data.get("message_id")
    reaction = request.data.get("reaction")

    try:
        message = Message.objects.get(id=message_id)
        # Create or update the reaction
        reaction_obj, created = MessageReaction.objects.update_or_create(
            message=message,
            user=request.user,
            defaults={
                'reaction': reaction,
                'reacted_at': timezone.now()
            }
        )

        # Prepare data for WebSocket
        reaction_data = {
            'user_id': request.user.id,
            'reaction': reaction
        }

        # Send real-time reaction update to WebSocket group
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{message.thread.id}",
            {
                "type": "reaction.update",
                "message_id": message.id,
                "reactions": [reaction_data],
            }
        )

        return Response({
            "success": True,
            "reaction": reaction,
            "reacted_at": reaction_obj.reacted_at
        })
    except Message.DoesNotExist:
        return Response({"error": "Message not found"}, status=404)

class CombinedChatOverviewAPIView(APIView):
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
        base_url = request.build_absolute_uri('/')[:-1]

        # Step 1: Fetch all pinned chat IDs for current user
        pinned_chat_ids = set(
            PinnedChat.objects.filter(user=user).values_list('chat_group_id', flat=True)
        )

        # --- One-to-One Chats ---
        one_to_one_chats = ChatGroup.objects.filter(
            is_group=False,
            members=user,
            messages__isnull=False
        ).annotate(
            last_message_time=Max('messages__timestamp')
        ).order_by('-last_message_time').distinct()

        one_to_one_data = []

        for chat in one_to_one_chats:
            other = chat.get_other_user(user)
            if other:
                profile = getattr(other, 'userprofile', None)
                image_url = (
                    base_url + profile.profile_picture.url
                    if profile and profile.profile_picture else None
                )

                last_message = chat.messages.order_by('-timestamp').first()

                # Count unseen messages
                unseen_count = chat.messages.exclude(
                    seen_statuses__user=user
                ).exclude(
                    sender=user  # Don’t count messages sent by self
                ).count()

                one_to_one_data.append({
                    "chat_group_id": chat.id,
                    "user_id": other.id,
                    "name": other.get_full_name(),
                    "profile_picture": image_url,
                    "last_message": last_message.get_content() if last_message else None,
                    "last_message_time": last_message.timestamp if last_message else None,
                    "is_pinned": chat.id in pinned_chat_ids,
                    "unseen_count": unseen_count
                })

        # --- Group Chats ---
        group_chats = ChatGroup.objects.filter(
            is_group=True,
            members=user
        ).annotate(
            last_message_time=Max('messages__timestamp')
        ).order_by('-last_message_time')

        group_data = []

        for group in group_chats:
            last_message = group.messages.order_by('-timestamp').first()
            last_message_text = decrypt_text(last_message.content_encrypted) if last_message and last_message.content_encrypted else None

            group_image_url = (
                base_url + group.group_profile_picture.url
                if group.group_profile_picture else None
            )

            # Count unseen messages in group
            unseen_count = group.messages.exclude(
                seen_statuses__user=user
            ).exclude(
                sender=user
            ).count()

            group_data.append({
                "chat_group_id": group.id,
                "group_name": group.name,
                "member_count": group.members.count(),
                "last_message": last_message_text,
                "last_message_time": last_message.timestamp if last_message else None,
                "group_profile_picture": group_image_url,
                "is_pinned": group.id in pinned_chat_ids,
                "unseen_count": unseen_count
            })

        return Response({
            "one_to_one_chats": one_to_one_data,
            "group_chats": group_data
        })

class TogglePinChatAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_group_id):
        user = request.user
        try:
            chat_group = ChatGroup.objects.get(id=chat_group_id)
        except ChatGroup.DoesNotExist:
            return Response({"error": "Chat group not found"}, status=status.HTTP_404_NOT_FOUND)

        pin, created = PinnedChat.objects.get_or_create(user=user, chat_group=chat_group)
        if not created:
            pin.delete()
            return Response({"message": "Chat unpinned"})
        return Response({"message": "Chat pinned"})


class AddGroupMembersAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        group = get_object_or_404(ChatGroup, id=group_id)

        # ✅ Ensure only group chats can add members
        if not group.is_group:
            return Response(
                {"status": False, "message": "Cannot add members to a 1-on-1 chat."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ✅ Ensure only group creator or existing members can add others
        if request.user != group.created_by:
            return Response(
                {"status": False, "message": "Only the group admin can add members."},
                status=status.HTTP_403_FORBIDDEN
            )

        # ✅ Expect list of user_ids in request
        user_ids = request.data.get("user_ids", [])
        if not isinstance(user_ids, list) or not user_ids:
            return Response(
                {"status": False, "message": "Please provide a list of user_ids."},
                status=status.HTTP_400_BAD_REQUEST
            )

        added_users = []
        for user_id in user_ids:
            try:
                user = User.objects.get(id=user_id)   # ✅ Now it will work
                group.members.add(user)
                added_users.append(user.full_name or user.email)
            except User.DoesNotExist:
                continue  # skip invalid IDs

        return Response({
            "status": True,
            "message": f"Added {len(added_users)} new members to the group.",
            "added_members": added_users,
            "group_id": group.id,
            "group_name": group.name,
        }, status=status.HTTP_200_OK)


class ChatGroupDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, group_id):
        group = get_object_or_404(ChatGroup, id=group_id)

        # ✅ Only group members can view details
        if request.user not in group.members.all():
            return Response({"status": False, "message": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

        serializer = ChatGroupSerializer(group, context={"request": request})
        return Response({"status": True, "data": serializer.data}, status=status.HTTP_200_OK)

    def put(self, request, group_id):
        group = get_object_or_404(ChatGroup, id=group_id)

        # ✅ Only admin can update
        if request.user != group.created_by:
            return Response(
                {"status": False, "message": "Only the group admin can update group details."},
                status=status.HTTP_403_FORBIDDEN
            )

        group_name = request.data.get("name")
        group_profile_picture = request.FILES.get("group_profile_picture")

        if group_name:
            group.name = group_name
        if group_profile_picture:
            group.group_profile_picture = group_profile_picture

        group.save()

        serializer = ChatGroupSerializer(group, context={"request": request})
        return Response({
            "status": True,
            "message": "Group details updated successfully.",
            "data": serializer.data
        }, status=status.HTTP_200_OK)
    

# class UploadMessageAPIView(APIView):
#     permission_classes = [IsAuthenticated]

#     def post(self, request, chat_group_id):
#         chat_group = get_object_or_404(ChatGroup, id=chat_group_id)

#         text = request.data.get("message", "").strip()
#         media_file = request.FILES.get("media")

#         if not text and not media_file:
#             return Response({"error": "Message or media required"}, status=400)

#         message = Message(thread=chat_group, sender=request.user)
#         if text:
#             message.set_content(text)
#         if media_file:
#             message.media = media_file
#         message.save()

#         serializer = MessageSerializer(message)
#         return Response(serializer.data, status=201)

class MediaMessageUploadAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        group_id = request.data.get("group_id")
        try:
            chat_group = ChatGroup.objects.get(id=group_id, members=request.user)
        except ChatGroup.DoesNotExist:
            return Response({"error": "Chat group not found or access denied"}, status=403)

        data = request.data.copy()
        data["sender"] = request.user.id
        data["thread"] = chat_group.id

        # ✅ Pass request into serializer context
        serializer = MessageSerializer(data=data, context={"request": request})
        if serializer.is_valid():
            message = serializer.save()

            # 🔔 Notify WebSocket group
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"chat_{chat_group.id}",
                {
                    "type": "chat_media_message",
                    "message_id": message.id,
                    "sender_id": request.user.id,
                    "message": message.get_content(),
                    "media_url": request.build_absolute_uri(message.media.url) if message.media else None,  # ✅ full URL
                    "timestamp": message.timestamp.isoformat(),
                }
            )

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DeleteMessageAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, message_id):
        user = request.user

        # Fetch message
        message = get_object_or_404(Message, id=message_id)

        # Only sender can delete
        if message.sender != user:
            return Response(
                {"detail": "You cannot delete this message."},
                status=status.HTTP_403_FORBIDDEN
            )

        thread_id = message.thread.id
        message_id = message.id

        # Hard delete (remove from DB)
        message.delete()

        # Trigger WebSocket event
        from asgiref.sync import async_to_sync
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"chat_{thread_id}",
            {
                "type": "chat.message_deleted",
                "message_id": message_id,
            }
        )

        return Response({"detail": "Message deleted successfully."}, status=status.HTTP_200_OK)
