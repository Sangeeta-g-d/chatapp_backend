# utils/serializer_utils.py

from django.utils.timezone import localtime
from datetime import timezone, timedelta

class SerializerUtils:

    @staticmethod
    def get_media_url(obj, context):
        request = context.get('request')
        if obj.media and hasattr(obj.media, 'url'):
            return request.build_absolute_uri(obj.media.url)
        return None

    @staticmethod
    def format_datetime_ist(dt):
        if dt is None:
            return None
        ist_offset = timezone(timedelta(hours=5, minutes=30))
        ist_time = localtime(dt).astimezone(ist_offset)
        return ist_time.strftime('%Y-%m-%d %H:%M:%S')
