import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.utils import timezone

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
            elif message_type == 'reaction':
                await self.handle_reaction(data)
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
            message_obj = await self.save_message(self.chat_group_id, sender_id, message)
            if message_obj:
                decrypted_content = await self.get_message_content(message_obj)

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
                
                # 🔹 Send Push Notification - Fire and forget (don't block message delivery)
                asyncio.create_task(self.send_push_notification(message_obj, decrypted_content))

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
            
            print(f"[FCM] Found {len(recipients_devices)} devices to notify")
            
            # Import FCM function
            from .firebase_utils import send_fcm_notification
            
            # Send notifications to all devices
            for device_info in recipients_devices:
                try:
                    print(f"[FCM] Sending to device: {device_info['token'][:20]}...")
                    
                    # Run FCM send in thread pool to avoid blocking
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        send_fcm_notification,
                        device_info['token'],
                        f"New message from {sender_name}",
                        decrypted_content[:50],
                        {
                            "chat_group_id": str(message_obj.thread.id),
                            "message_id": str(message_obj.id),
                        }
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
                'recipients_devices': recipients_devices
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