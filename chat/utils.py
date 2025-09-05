from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

def send_ws_event(group_name, event_type, data):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "chat.message",
            "event": event_type,
            "data": data,
        }
    )
