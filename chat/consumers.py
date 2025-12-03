import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.utils import timezone
from chat.models import UserStatus

from .models import ChatGroup, Message, MessageSeenStatus, MessageReaction

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
            await self.set_user_online()
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()

            await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "presence_update",
                "user_id": self.user.id,
                "is_online": True,
                "last_active": timezone.now().isoformat()
            }
            )

    async def disconnect(self, close_code):
        print(f"[WebSocket] User {self.user.id} disconnected from chat group {self.chat_group_id}")
        await self.set_user_offline()

        await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "presence_update",
                    "user_id": self.user.id,
                    "is_online": False,
                    "last_active": timezone.now().isoformat()
                }
            )
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
            elif message_type == 'reaction':
                await self.handle_reaction(data)

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
            # Save message
            message_obj = await self.save_message(self.chat_group_id, sender_id, message)

            if message_obj:
                decrypted_content = await self.get_message_content(message_obj)

                # 🔹 1. Broadcast normal chat message inside the chat room
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': decrypted_content,
                        'sender_id': sender_id,
                        'message_id': message_obj.id,
                        'timestamp': message_obj.timestamp.isoformat(),
                    }
                )

                # 🔹 2. Notify sender's inbox WS (PresenceConsumer)
                await self.channel_layer.group_send(
                    f"user_{sender_id}",
                    {
                        "type": "chat_list_update",
                        "chat_group_id": self.chat_group_id,
                        "last_message": decrypted_content,
                        "last_message_time": message_obj.timestamp.isoformat(),
                        "sender_id": sender_id,
                    }
                )

                # 🔹 3. Notify all other group members' inbox WS
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
                            "last_message_time": message_obj.timestamp.isoformat(),
                            "sender_id": sender_id,
                        }
                    )

                # 🔹 4. Push Notification (non-blocking)
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
    
    async def handle_media_message(self, data):
        message_id = data.get('message_id')
        sender_id = data.get('sender_id')
        message = data.get('message')
        media_url = data.get('media_url')
        timestamp = data.get('timestamp')

        if not media_url:
            print("[Error] Media notification without media_url")
            return

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
        
    async def chat_media_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'media_message',
            'message_id': event['message_id'],
            'sender_id': event['sender_id'],
            'message': event.get('message'),
            'media_url': event['media_url'],
            'timestamp': event['timestamp'],
        }))

    async def chat_message_deleted(self, event):
        await self.send(text_data=json.dumps({
            "type": "message_deleted",
            "message_id": event["message_id"],
        }))

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

    

    @database_sync_to_async
    def set_user_online(self):
        from chat.models import UserStatus
        status, created = UserStatus.objects.get_or_create(user=self.user)
        status.is_online = True
        status.save(update_fields=["is_online"])

    @database_sync_to_async
    def set_user_offline(self):
        self.user.status.is_online = False
        self.user.status.last_active = timezone.now()
        self.user.status.save()

    async def presence_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "presence",
            "user_id": event["user_id"],
            "is_online": event["is_online"],
            "last_active": event["last_active"]
        }))


    @database_sync_to_async
    def save_message(self, group_id, sender_id, message):
        try:
            chat_group = ChatGroup.objects.get(id=group_id)
            sender = User.objects.get(id=sender_id)
            msg = Message(thread=chat_group, sender=sender)
            msg.set_content(message)
            msg.save()
            return msg
        except Exception as e:
            print(f"[Error] Saving message failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    @database_sync_to_async
    def get_message_content(self, message_obj):
        try:
            return message_obj.get_content()
        except Exception as e:
            print(f"[Error] Decrypting message failed: {e}")
            return "Error"

    # -------------------- Seen Status --------------------

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

    # -------------------- Reactions --------------------

    async def handle_reaction(self, data):
        message_id = data.get('message_id')
        user_id = data.get('user_id')
        reaction = data.get('reaction')

        if message_id and user_id and reaction:
            await self.save_reaction(message_id, user_id, reaction)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'reaction_update',
                    'message_id': message_id,
                    'user_id': user_id,
                    'reaction': reaction,
                }
            )

    async def reaction_update(self, event):
        await self.send(text_data=json.dumps({
            'type': 'reaction',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'reaction': event['reaction'],
        }))

    @database_sync_to_async
    def save_reaction(self, message_id, user_id, reaction):
        try:
            message = Message.objects.get(id=message_id)
            user = User.objects.get(id=user_id)
            MessageReaction.objects.update_or_create(
                message=message,
                user=user,
                defaults={'reaction': reaction}
            )
        except Exception as e:
            print(f"[Error] Saving reaction failed: {e}")

    # -------------------- Push Notification --------------------
    
    async def send_push_notification(self, message_obj, decrypted_content):
        """
        Send FCM notifications to all group members except sender
        """
        try:
            print(f"[FCM] Starting notification for message {message_obj.id}")
            
            # Get notification data using database_sync_to_async
            notification_data = await self.get_notification_data(message_obj)
            
            if not notification_data:
                print("[FCM] No notification data retrieved")
                return
            
            sender_name = notification_data['sender_name']
            recipients_devices = notification_data['recipients_devices']
            sender_id = notification_data['sender_id'] 
            print(f"[FCM] Sender ID: {sender_id}")
            print(f"[FCM] Found {len(recipients_devices)} devices to notify")
            
            # Import FCM function
            from .firebase_utils import send_fcm_notification
                    # Use group name as title for group messages, otherwise sender name
            title = getattr(message_obj.thread, "name", None) if getattr(message_obj.thread, "is_group", False) else sender_name
            # Send notifications to all devices
            for device_info in recipients_devices:
                try:
                    print(f"[FCM] Sending to device: {device_info['token'][:20]}...")
                    data_payload = {
                        "message_id": str(message_obj.id),
                        "sender_id": str(sender_id)
                    }
                    if getattr(message_obj.thread, "is_group", False):
                        data_payload["chat_group_id"] = str(message_obj.thread.id)
                    # Run FCM send in thread pool to avoid blocking
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        send_fcm_notification,
                        device_info['token'],
                        title,
                        decrypted_content[:50],
                        data_payload
                    )
                    print(f"[FCM] Successfully sent to {device_info['user_email']}")
                    
                except Exception as device_error:
                    print(f"[FCM Error] Failed for device {device_info.get('user_email', 'unknown')}: {device_error}")
                    import traceback
                    traceback.print_exc()
                    
        except Exception as e:
            print(f"[FCM Error] Push notification failed: {e}")
            import traceback
            traceback.print_exc()
    
    @database_sync_to_async
    def get_notification_data(self, message_obj):
        """
        Fetch all data needed for notifications in one database query
        """
        try:
            group = message_obj.thread
            sender = message_obj.sender
            sender_name = sender.get_full_name() or sender.username
            sender_id = sender.id
            
            # Get all recipients (members except sender)
            recipients = group.members.exclude(id=sender.id)
            
            # Collect all device tokens
            recipients_devices = []
            for user in recipients:
                for device in user.devices.all():
                    recipients_devices.append({
                        'token': device.device_token,
                        'user_email': user.email,
                        'user_id': user.id
                    })
            
            print(f"[FCM] Sender: {sender_name}, Recipients: {[r['user_email'] for r in recipients_devices]}")
            
            return {
                'sender_name': sender_name,
                'recipients_devices': recipients_devices,
                'sender_id': sender_id,
            }
            
        except Exception as e:
            print(f"[FCM Error] Failed to get notification data: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @database_sync_to_async
    def get_user_devices(self, user):
        """Legacy method - can be removed if not used elsewhere"""
        return list(user.devices.all())
    



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

        # GLOBAL ONLINE USERS GROUP
        self.global_group = "online_users"

        await self.channel_layer.group_add(
            self.global_group,
            self.channel_name
        )

        await self.set_user_online()

        # USER PERSONAL ROOM (existing)
        self.user_room = f"user_{self.user.id}"

        await self.channel_layer.group_add(
            self.user_room,
            self.channel_name
        )

        # Broadcast to all users that this user is now online
        await self.channel_layer.group_send(
            self.global_group,
            {
                "type": "user_status_update",
                "user_id": self.user.id,
                "is_online": True,
            }
        )

        await self.accept()


    async def disconnect(self, code):

        # Remove from global online user group
        await self.channel_layer.group_discard(
            self.global_group,
            self.channel_name
        )

        await self.set_user_offline()

        await self.channel_layer.group_discard(
            self.user_room,
            self.channel_name
        )

        # Broadcast user offline
        await self.channel_layer.group_send(
            self.global_group,
            {
                "type": "user_status_update",
                "user_id": self.user.id,
                "is_online": False,
            }
        )


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


    # ------------------------------------------
    # NEW HANDLER FOR GLOBAL ONLINE/OFFLINE EVENT
    # ------------------------------------------
    async def user_status_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "user_status_update",
            "user_id": event["user_id"],
            "is_online": event["is_online"],
        }))


    # ------------------------------------------
    # Existing functionality below (UNCHANGED)
    # ------------------------------------------

    async def chat_list_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "chat_list_update",
            "chat_group_id": event["chat_group_id"],
            "last_message": event["last_message"],
            "last_message_time": event["last_message_time"],
            "sender_id": event["sender_id"],
        }))

    async def permission_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "permission_update",
            "permissions": event.get("data")
        }))
