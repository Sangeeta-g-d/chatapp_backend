from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import pytz
from django.utils import timezone
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


def to_saudi_time(dt):
    if dt is None:
        return None
    sa_tz = pytz.timezone("Asia/Riyadh")
    return timezone.localtime(dt, sa_tz)