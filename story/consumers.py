from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import StoryModel, StoryView
from admin_part.models import CustomUser  # Adjust if needed

class StoryConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_authenticated:
            await self.accept()
        else:
            await self.close()

    async def receive_json(self, content):
        action = content.get("action")
        story_id = content.get("story_id")

        if action == "view_story" and story_id:
            await self.mark_story_as_viewed(story_id)

            # Broadcast to the story owner's group
            story = await self.get_story(story_id)
            if story:
                await self.channel_layer.group_send(
                    f"story_user_{story.user.id}",
                    {
                        "type": "story.viewed",
                        "story_id": story_id,
                        "viewer": {
                            "user_id": self.user.id,
                            "full_name": self.user.get_full_name(),
                            "profile_picture": self.user.userprofile.profile_picture.url if hasattr(self.user, 'userprofile') and self.user.userprofile.profile_picture else None,
                            "viewed_at": timezone.now().astimezone().strftime('%Y-%m-%d %H:%M:%S')
                        }
                    }
                )

    async def story_viewed(self, event):
        await self.send_json({
            "event": "story_viewed",
            "story_id": event["story_id"],
            "viewer": event["viewer"]
        })

    async def disconnect(self, close_code):
        pass

    @database_sync_to_async
    def mark_story_as_viewed(self, story_id):
        story = StoryModel.objects.filter(id=story_id, expires_at__gt=timezone.now()).first()
        if story:
            StoryView.objects.get_or_create(story=story, user=self.user)

    @database_sync_to_async
    def get_story(self, story_id):
        return StoryModel.objects.select_related("user").filter(id=story_id).first()
