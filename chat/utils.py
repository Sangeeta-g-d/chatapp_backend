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

import pytz
from django.utils import timezone

TIME_ZONE = "Asia/Riyadh"
USE_TZ = True


def to_saudi_time(dt):
    """
    Convert datetime to Saudi Arabia timezone (Asia/Riyadh).
    Handles naive and aware datetime objects.
    """
    if dt is None:
        return None
    
    sa_tz = pytz.timezone("Asia/Riyadh")
    
    # If dt is naive (no timezone), assume it's in UTC
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, pytz.UTC)
    
    # Convert to Saudi timezone
    return dt.astimezone(sa_tz)


def format_saudi_time(dt, format_str="%Y-%m-%d %H:%M:%S"):
    """
    Convert to Saudi time and format as string.
    """
    saudi_time = to_saudi_time(dt)
    if saudi_time:
        return saudi_time.strftime(format_str)
    return None

from datetime import datetime

def saudi_timestamp(dt):
    if dt is None:
        return None
    
    # if dt is already a string — try parsing
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", ""))
        except:
            return dt    # fallback: just return original string
    
    saudi = to_saudi_time(dt)
    return saudi.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if saudi else None
