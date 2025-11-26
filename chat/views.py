# views.py
from rest_framework.views import APIView
from django.shortcuts import render
from rest_framework.permissions import IsAuthenticated
from django.db.models import Max, F
from rest_framework.response import Response
from django.db.models.functions import Coalesce
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
from .firebase_utils import send_fcm_notification  # your helper function
from feeds.pagination import SafePageNumberPagination


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

        # Fetch messages (paginated) ------------------------------------------------
        messages_qs = Message.objects.filter(
            thread=chat_group
        ).prefetch_related(
            'seen_statuses',
            # 'reactions',  # 🚫 Commented out
            'sender'
        ).order_by('id')

        paginator = SafePageNumberPagination()
        paginator.page_size = 20                      # default page size
        paginator.page_query_param = "page"           # allow ?page=NN
        paginator.page_size_query_param = "page_size" # optional ?page_size=
        paginator.max_page_size = 100

        # paginate_queryset will return an actual page's object_list or an empty list
        # (SafePageNumberPagination handles invalid pages and sets paginator.page accordingly)
        page_messages = paginator.paginate_queryset(messages_qs, request)

        messages_data = []
        for msg in page_messages:
            seen_data = [{
                "user_id": seen.user.id,
                "seen_at": seen.seen_at
            } for seen in msg.seen_statuses.all()]

            messages_data.append({
                "id": msg.id,
                "sender_id": msg.sender.id,
                "sender_name": msg.sender.full_name,
                "message": msg.get_content(),
                "media": request.build_absolute_uri(msg.media.url) if msg.media else None,
                "timestamp": msg.timestamp,
                "seen_status": seen_data,
                "is_seen": msg.seen_statuses.filter(user=current_user).exists(),
            })

        # compute pagination meta without breaking response on invalid page
        try:
            total_count = paginator.page.paginator.count
            current_page_number = getattr(paginator.page, "number", 1)
        except Exception:
            # fallback: return correct total and requested page param
            total_count = messages_qs.count()
            current_page_number = int(request.query_params.get("page", 1) or 1)

        group_profile_url = (
            request.build_absolute_uri(chat_group.group_profile_picture.url)
            if chat_group.group_profile_picture
            else None
        )

        response_data = {
            "chat_group_id": chat_group.id,
            "can_share_media": current_user.can_share_media,
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
            "pagination": {                                 # optional meta (keeps response shape)
                "total_count": total_count,
                "page": current_page_number,
                "page_size": paginator.get_page_size(request),
            }
        }

        return Response(response_data, status=status.HTTP_200_OK)

    
class CreateGroupChatAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = GroupChatCreateSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            group = serializer.save()

            # 🔹 Send FCM notification to group members
            self.notify_group_members(group)

            return Response({
                "message": "Group chat created successfully.",
                "group_id": group.id,
                "name": group.name,
                "members": [user.id for user in group.members.all()],
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def notify_group_members(self, group):
        for member in group.members.all():
            # skip the creator
            if member == group.created_by:
                continue
            # send notification to all devices of this user
            for device in member.devices.all():
                send_fcm_notification(
                    token=device.device_token,
                    title="New Group Chat",
                    body=f"You have been added to the group '{group.name}'",
                    data={"group_id": str(group.id)}
                )

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

        # --- Check if user suspended ---
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

        # --- Get pinned chats ---
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
            if not other:
                continue

            profile = getattr(other, 'userprofile', None)
            image_url = base_url + profile.profile_picture.url if profile and profile.profile_picture else None

            last_message = chat.messages.order_by('-timestamp').first()
            unseen_count = chat.messages.exclude(
                seen_statuses__user=user
            ).exclude(
                sender=user
            ).count()

            # 🟢 Handle last message: text or media
            if last_message:
                if last_message.media:
                    last_message_display = base_url + last_message.media.url
                    message_type = "media"
                elif last_message.content_encrypted:
                    last_message_display = last_message.get_content()
                    message_type = "text"
                else:
                    last_message_display = None
                    message_type = None
            else:
                last_message_display = None
                message_type = None

            one_to_one_data.append({
                "chat_group_id": chat.id,
                "user_id": other.id,
                "name": other.get_full_name(),
                "profile_picture": image_url,
                "last_message": last_message_display,
                "last_message_type": message_type,
                "last_message_time": last_message.timestamp if last_message else None,
                "is_pinned": chat.id in pinned_chat_ids,
                "unseen_count": unseen_count,
            })

        # --- Group Chats ---
        group_chats = (
            ChatGroup.objects.filter(is_group=True, members=user)
            .annotate(last_message_time=Coalesce(Max('messages__timestamp'), F('created_at')))
            .order_by('-last_message_time')
        )

        group_data = []
        for group in group_chats:
            last_message = group.messages.order_by('-timestamp').first()

            if last_message:
                if last_message.media:
                    last_message_text = base_url + last_message.media.url
                    message_type = "media"
                elif last_message.content_encrypted:
                    last_message_text = decrypt_text(last_message.content_encrypted)
                    message_type = "text"
                else:
                    last_message_text = None
                    message_type = None
            else:
                last_message_text = None
                message_type = None

            group_image_url = base_url + group.group_profile_picture.url if group.group_profile_picture else None
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
                "last_message_type": message_type,
                "last_message_time": last_message.timestamp if last_message else None,
                "group_profile_picture": group_image_url,
                "is_pinned": group.id in pinned_chat_ids,
                "unseen_count": unseen_count,
            })

        return Response({
            "one_to_one_chats": one_to_one_data,
            "group_chats": group_data,
        })

MAX_PINNED_CHATS = 4 

class TogglePinChatAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, chat_group_id):
        user = request.user
        try:
            chat_group = ChatGroup.objects.get(id=chat_group_id)
        except ChatGroup.DoesNotExist:
            return Response({"error": "Chat group not found"}, status=status.HTTP_404_NOT_FOUND)

        # Check if this chat is already pinned
        pin_exists = PinnedChat.objects.filter(user=user, chat_group=chat_group).first()
        if pin_exists:
            pin_exists.delete()
            return Response({"message": "Chat unpinned"})

        # Count current pinned chats
        pinned_count = PinnedChat.objects.filter(user=user).count()
        if pinned_count >= MAX_PINNED_CHATS:
            return Response(
                {"error": f"You can pin a maximum of {MAX_PINNED_CHATS} chats."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create new pin
        PinnedChat.objects.create(user=user, chat_group=chat_group)
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


class RemoveUserFromGroupAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, group_id):
        """
        Removes a user from a chat group and sends FCM notification to the removed user.
        """
        current_user = request.user
        user_id_to_remove = request.data.get("user_id")

        if not user_id_to_remove:
            return Response({
                "status": 400,
                "message": "User ID is required."
            }, status=status.HTTP_400_BAD_REQUEST)

        chat_group = get_object_or_404(ChatGroup, id=group_id)

        # ✅ Check group type
        if not chat_group.is_group:
            return Response({
                "status": 400,
                "message": "Cannot remove users from a 1-1 chat."
            }, status=status.HTTP_400_BAD_REQUEST)

        # ✅ Check permission (only creator can remove)
        if chat_group.created_by != current_user:
            return Response({
                "status": 403,
                "message": "Only the group creator can remove members."
            }, status=status.HTTP_403_FORBIDDEN)

        # ✅ Get user to remove
        user_to_remove = get_object_or_404(CustomUser, id=user_id_to_remove)

        # ✅ Check if user is in group
        if not chat_group.members.filter(id=user_to_remove.id).exists():
            return Response({
                "status": 404,
                "message": "User is not a member of this group."
            }, status=status.HTTP_404_NOT_FOUND)

        # ✅ Remove user
        chat_group.members.remove(user_to_remove)

        # ✅ Send FCM notification
        devices = UserDevice.objects.filter(user=user_to_remove)
        title = "Removed from Chat Group"
        body = f"You have been removed from the group '{chat_group.name}'."
        data = {"chat_group_id": str(chat_group.id)}

        for device in devices:
            send_fcm_notification(device.device_token, title, body, data)

        return Response({
            "status": 200,
            "message": f"User '{user_to_remove.full_name}' removed successfully and notified.",
        }, status=status.HTTP_200_OK)



class DeleteChatGroupAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, group_id):
        """
        Deletes a chat group (by creator or admin) and sends notifications to members.
        """
        current_user = request.user
        chat_group = get_object_or_404(ChatGroup, id=group_id)

        # ✅ Only creator or admin can delete
        if chat_group.created_by != current_user and not current_user.is_staff:
            return Response({
                "status": 403,
                "message": "You do not have permission to delete this group."
            }, status=status.HTTP_403_FORBIDDEN)

        if not chat_group.is_group:
            return Response({
                "status": 400,
                "message": "1-1 chats cannot be deleted through this API."
            }, status=status.HTTP_400_BAD_REQUEST)

        # ✅ Notify members before deletion
        members = chat_group.members.all()
        title = "Group Deleted"
        body = f"The group '{chat_group.name}' has been deleted by the admin."
        data = {"chat_group_id": str(chat_group.id)}

        for member in members:
            devices = UserDevice.objects.filter(user=member)
            for device in devices:
                send_fcm_notification(device.device_token, title, body, data)

        # ✅ Delete group
        group_name = chat_group.name
        chat_group.delete()

        return Response({
            "status": 200,
            "message": f"Group '{group_name}' deleted successfully and members notified."
        }, status=status.HTTP_200_OK)


class UserStatusAPIView(APIView):
    def get(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
            status_obj = user.status

            return Response({
                "user_id": user.id,
                "is_online": status_obj.is_online,
                "last_active": status_obj.last_active
            })
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
