# ws.py

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def send_permission_update(user):
    channel_layer = get_channel_layer()
    
    data = {
        "can_add_story": user.can_add_story,
        "can_upload_feed": user.can_upload_feed,
        "can_share_media": user.can_share_media,
        "can_download_media": user.can_download_media,
        "can_access_web_app": user.can_access_web_app,
        "is_suspended": user.is_suspended,
    }

    async_to_sync(channel_layer.group_send)(
        f"user_{user.id}",
        {
            "type": "permission_update",
            "data": data,
        }
    )
