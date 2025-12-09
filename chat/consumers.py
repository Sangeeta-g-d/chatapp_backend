import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.utils import timezone
from chat.models import UserStatus
from .utils import to_saudi_time
from .models import ChatGroup, Message, MessageSeenStatus, MessageReaction
from .utils import saudi_timestamp
User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.chat_group_id = self.scope['url_route']['kwargs']['chat_group_id']
        self.room_group_name = f'chat_{self.chat_group_id}'
        self.user = self.scope["user"]
        
        if self.user == AnonymousUser():
            await self.close()
        else:
            print(f"[WebSocket] User {self.user.id} connected to chat group {self.chat_group_id}")
            
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()

    async def disconnect(self, close_code):
        print(f"[WebSocket] User {self.user.id} disconnected from chat group {self.chat_group_id}")

        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'message':
                await self.handle_new_message(data)
            elif message_type == 'media_message':
                await self.handle_media_message(data)
            elif message_type == 'seen':
                await self.handle_seen_status(data)
            elif message_type == "typing":
                await self.handle_typing(data)
            elif message_type == "typing_stop":
                await self.handle_typing_stop(data)
            else:
                print(f"[Error] Unknown message type received: {message_type}")

        except json.JSONDecodeError as e:
            print(f"[Error] JSON decode error: {e}")
        except Exception as e:
            print(f"[Error] Exception in receive: {e}")
            import traceback
            traceback.print_exc()

    # -------------------- Message Handling --------------------

    async def handle_new_message(self, data):
        message = data.get('message')
        sender_id = data.get('sender_id')

        if not message:
            print(f"[Error] Empty message received.")
            return

        if message and sender_id:
            # save_message implemented below
            message_obj = await self.save_message(self.chat_group_id, sender_id, message)

            if message_obj:
                # get_message_content implemented below
                decrypted_content = await self.get_message_content(message_obj)

                # Broadcast normal chat message to chat room
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': decrypted_content,
                        'sender_id': sender_id,
                        'message_id': message_obj.id,
                        'timestamp': to_saudi_time(message_obj.timestamp).isoformat()

                    }
                )

                # Notify sender inbox
                await self.channel_layer.group_send(
                    f"user_{sender_id}",
                    {
                        "type": "chat_list_update",
                        "chat_group_id": self.chat_group_id,
                        "last_message": decrypted_content,
                        "last_message_time": saudi_timestamp(message_obj.timestamp),
                        "sender_id": sender_id,
                    }
                )

                # Notify other users in inbox
                members = await database_sync_to_async(
                    lambda: list(
                        message_obj.thread.members.exclude(id=sender_id)
                        .values_list("id", flat=True)
                    )
                )()

                for member_id in members:
                    await self.channel_layer.group_send(
                        f"user_{member_id}",
                        {
                            "type": "chat_list_update",
                            "chat_group_id": self.chat_group_id,
                            "last_message": decrypted_content,
                            "last_message_time": saudi_timestamp(message_obj.timestamp),
                            "sender_id": sender_id,
                        }
                    )

                # Push Notification async
                asyncio.create_task(
                    self.send_push_notification(
                        message_obj, decrypted_content
                    )
                )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'sender_id': event['sender_id'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
        }))

    # -------------------- Media --------------------

    async def handle_media_message(self, data):
        message_id = data.get('message_id')
        sender_id = data.get('sender_id')
        message = data.get('message')
        media_url = data.get('media_url')
        timestamp = data.get('timestamp')

        if not media_url:
            print("[Error] Media notification without media_url")
            return
        # Broadcast media message to chat room
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                'type': 'chat_media_message',
                'message_id': message_id,
                'sender_id': sender_id,
                'message': message,
                'media_url': media_url,
                'timestamp': timestamp,
            }
        )

        # Also update inbox/chat list for sender and other members (so media appears in inbox preview)
        try:
            last_message_preview = message or 'Media'
            last_message_time = timestamp or timezone.now().isoformat()

            # Notify sender's inbox (their personal user_{id} group)
            await self.channel_layer.group_send(
                f"user_{sender_id}",
                {
                    "type": "chat_list_update",
                    "chat_group_id": self.chat_group_id,
                    "last_message": last_message_preview,
                    "last_message_time": saudi_timestamp(last_message_time),
                    "sender_id": sender_id,
                    "is_media": True,
                    "media_url": media_url,
                }
            )

            # Fetch other member ids asynchronously
            members = await database_sync_to_async(
                lambda: list(
                    ChatGroup.objects.get(id=self.chat_group_id).members.exclude(id=sender_id)
                    .values_list("id", flat=True)
                )
            )()

            for member_id in members:
                await self.channel_layer.group_send(
                    f"user_{member_id}",
                    {
                        "type": "chat_list_update",
                        "chat_group_id": self.chat_group_id,
                        "last_message": last_message_preview,
                        "last_message_time": saudi_timestamp(last_message_time),
                        "sender_id": sender_id,
                        "is_media": True,
                        "media_url": media_url,
                    }
                )
        except Exception as e:
            print(f"[Error] notifying inbox for media message: {e}")
        
    async def chat_media_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'media_message',
            'message_id': event['message_id'],
            'sender_id': event['sender_id'],
            'message': event.get('message'),
            'media_url': event['media_url'],
            'timestamp': event['timestamp'],
        }))

    # -------------------- Typing --------------------

    async def handle_typing(self, data):
        user_id = data.get("user_id")

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "typing_event",
                "user_id": user_id,
                "is_typing": True
            }
        )

    async def handle_typing_stop(self, data):
        user_id = data.get("user_id")
    
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "typing_event",
                "user_id": user_id,
                "is_typing": False
            }
        )
    
    async def typing_event(self, event):
        await self.send(text_data=json.dumps({
            "type": "typing",
            "user_id": event["user_id"],
            "is_typing": event["is_typing"]
        }))

    # -------------------- Seen --------------------

    async def handle_seen_status(self, data):
        message_id = data.get('message_id')
        user_id = data.get('user_id')

        if message_id and user_id:
            await self.save_seen_status(message_id, user_id)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'seen_status',
                    'message_id': message_id,
                    'user_id': user_id,
                }
            )

    async def seen_status(self, event):
        await self.send(text_data=json.dumps({
            'type': 'seen',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
        }))

    @database_sync_to_async
    def save_seen_status(self, message_id, user_id):
        try:
            message = Message.objects.get(id=message_id)
            user = User.objects.get(id=user_id)
            MessageSeenStatus.objects.update_or_create(
                message=message,
                user=user,
                defaults={'seen_at': timezone.now()}
            )
        except Exception as e:
            print(f"[Error] Saving seen status failed: {e}")

    # -------------------- Push Notification --------------------
    # Kept untouched

    async def send_push_notification(self, message_obj, decrypted_content):
        try:
            print(f"[FCM] Starting notification for message {message_obj.id}")
            notification_data = await self.get_notification_data(message_obj)
            
            if not notification_data:
                print("[FCM] No notification data retrieved")
                return
           
            sender_name = notification_data['sender_name']
            recipients_devices = notification_data['recipients_devices']
            sender_id = notification_data['sender_id'] 
            
            from .firebase_utils import send_fcm_notification
            
            title = (
                getattr(message_obj.thread, "name", None)
                if getattr(message_obj.thread, "is_group", False)
                else sender_name
            )

            for device_info in recipients_devices:
                try:
                    data_payload = {
                        "message_id": str(message_obj.id),
                        "sender_id": str(sender_id)
                    }
                    if getattr(message_obj.thread, "is_group", False):
                        data_payload["chat_group_id"] = str(message_obj.thread.id)

                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        send_fcm_notification,
                        device_info['token'],
                        title,
                        decrypted_content[:50],
                        data_payload
                    )
                except Exception:
                    import traceback; traceback.print_exc()
                    
        except Exception:
            import traceback; traceback.print_exc()

    @database_sync_to_async
    def get_notification_data(self, message_obj):
        try:
            group = message_obj.thread
            sender = message_obj.sender
            sender_name = sender.get_full_name() or sender.username
            sender_id = sender.id
            
            recipients = group.members.exclude(id=sender.id)
            
            recipients_devices = []
            for user in recipients:
                for device in user.devices.all():
                    recipients_devices.append({
                        'token': device.device_token,
                        'user_email': user.email,
                        'user_id': user.id
                    })

            return {
                'sender_name': sender_name,
                'recipients_devices': recipients_devices,
                'sender_id': sender_id,
            }
        except Exception:
            import traceback; traceback.print_exc()
            return None

    # -------------------- NEW: Save Message & Get Content Helpers --------------------
    # These are the missing methods that caused the AttributeError.
    # They run DB operations through database_sync_to_async to be safe in async context.

    @database_sync_to_async
    def save_message(self, chat_group_id, sender_id, raw_message):
        """
        Create and save a Message instance for the chat group and return it.
        - chat_group_id: string or int (from URL)
        - sender_id: int
        - raw_message: plaintext message (will be encrypted via Message.set_content)
        Returns Message instance or None on failure.
        """
        try:
            # Safely fetch chat group and user
            thread = ChatGroup.objects.get(id=chat_group_id)
            sender = User.objects.get(id=sender_id)

            # Create message
            msg = Message(thread=thread, sender=sender)
            # Use model's set_content helper (assumed to encrypt)
            if hasattr(msg, "set_content"):
                msg.set_content(raw_message)
            else:
                # Fallback: store raw text in content_encrypted if set_content missing
                msg.content_encrypted = raw_message

            msg.save()

            # If you need to prefetch related fields used later, do it here
            msg.thread = thread  # ensure thread attribute available
            return msg
        except ChatGroup.DoesNotExist:
            print(f"[Error] ChatGroup with id {chat_group_id} does not exist.")
        except User.DoesNotExist:
            print(f"[Error] User with id {sender_id} does not exist.")
        except Exception as e:
            print(f"[Error] Saving message failed: {e}")
            import traceback; traceback.print_exc()
        return None

    @database_sync_to_async
    def get_message_content(self, message_obj):
        """
        Given a Message model instance (or object with .id), fetch fresh and return decrypted content.
        Returns string (possibly empty) or None.
        """
        try:
            # Re-fetch from DB to avoid stale/async issues
            msg = Message.objects.get(id=message_obj.id)
            if hasattr(msg, "get_content"):
                return msg.get_content() or ""
            # fallback to content_encrypted if decryption helper missing
            return getattr(msg, "content_encrypted", "") or ""
        except Message.DoesNotExist:
            print(f"[Error] Message with id {getattr(message_obj, 'id', None)} does not exist.")
        except Exception as e:
            print(f"[Error] Getting message content failed: {e}")
            import traceback; traceback.print_exc()
        return ""

class QRLoginConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.session_id = self.scope['url_route']['kwargs']['session_id']
        self.group_name = f"qr_{self.session_id}"

        # Join websocket group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    # Event received when backend approves QR
    async def qr_login_approved(self, event):
        await self.send(text_data=json.dumps(event["data"]))


class PresenceConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            return await self.close()

        # GLOBAL ONLINE GROUP
        self.global_group = "online_users"
        await self.channel_layer.group_add(self.global_group, self.channel_name)

        # USER PERSONAL ROOM
        self.user_room = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.user_room, self.channel_name)

        # DB update
        await self.set_user_online()

        # Broadcast online status
        await self.channel_layer.group_send(
            self.global_group,
            {
                "type": "user_status_update",
                "user_id": self.user.id,
                "is_online": True,
                "last_active": saudi_timestamp(timezone.now()),
            }
        )

        # Accept WebSocket
        await self.accept()

        # Start heartbeat every 20 seconds
        self.heartbeat_task = asyncio.create_task(self.send_heartbeat())


    async def disconnect(self, code):
        # Stop heartbeat loop
        try:
            self.heartbeat_task.cancel()
        except:
            pass

        # DB update
        await self.set_user_offline()

        # Remove from groups
        await self.channel_layer.group_discard(self.global_group, self.channel_name)
        await self.channel_layer.group_discard(self.user_room, self.channel_name)

        # Broadcast offline status
        await self.channel_layer.group_send(
            self.global_group,
            {
                "type": "user_status_update",
                "user_id": self.user.id,
                "is_online": False,
                "last_active": saudi_timestamp(timezone.now()),

            }
        )


    # ---------------------------
    # HEARTBEAT (ANTI TIMEOUT)
    # ---------------------------
    async def send_heartbeat(self):
        while True:
            try:
                await self.send(json.dumps({"type": "ping"}))
                await asyncio.sleep(20)
            except Exception:
                break


    # ---------------------------
    # DATABASE STATUS HELPERS
    # ---------------------------
    @database_sync_to_async
    def set_user_online(self):
        status, _ = UserStatus.objects.get_or_create(user=self.user)
        status.is_online = True
        status.last_active = timezone.now()
        status.save()

    @database_sync_to_async
    def set_user_offline(self):
        if hasattr(self.user, "status"):
            self.user.status.is_online = False
            self.user.status.last_active = timezone.now()
            self.user.status.save()


    # ---------------------------
    # ONLINE/OFFLINE BROADCAST
    # ---------------------------
    async def user_status_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "user_status_update",
            "user_id": event["user_id"],
            "is_online": event["is_online"],
            "last_active": event.get("last_active"),
        }))


    # ---------------------------
    # EXISTING FEATURE HANDLERS
    # ---------------------------
    async def chat_list_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "chat_list_update",
            "chat_group_id": event["chat_group_id"],
            "last_message": event["last_message"],
            "last_message_time": (event["last_message_time"]),
            "sender_id": event["sender_id"],
            "is_media": event.get("is_media", False),
            "media_url": event.get("media_url"),
        }))

    async def permission_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "permission_update",
            "permissions": event.get("data")
        }))