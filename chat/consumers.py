import json
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
from cryptography.fernet import Fernet

from .models import ChatGroup, Message, MessageSeenStatus, MessageReaction

User = get_user_model()


# --- Encryption Utilities ---
def decrypt_text(encrypted):
    key = settings.ENCRYPTION_KEY.encode()
    fernet = Fernet(key)
    try:
        return fernet.decrypt(encrypted.encode()).decode()
    except:
        return "[Message could not be decrypted]"


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
            elif message_type == 'media_message':  # notify about media
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

    # -------------------- Message Handling --------------------

    async def handle_new_message(self, data):
        message = data.get('message')
        sender_id = data.get('sender_id')
        media_url = data.get('media_url')
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

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'message',
            'message': event['message'],
            'sender_id': event['sender_id'],
            'message_id': event['message_id'],
            'timestamp': event['timestamp'],
        }))
    
    async def handle_media_message(self, data):
    # These values come from API response
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
            "delete_for_everyone": event["delete_for_everyone"],
            "deleted_for_user_id": event.get("deleted_for_user_id"),
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
