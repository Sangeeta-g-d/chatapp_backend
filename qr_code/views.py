# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status
import pytz
from django.utils import timezone
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import QRSession
from admin_part.models import UserProfile

class CreateQRSessionAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        ttl_seconds = 120
        expires_at = timezone.now() + timedelta(seconds=ttl_seconds)

        # Convert to Saudi Time
        saudi_tz = pytz.timezone("Asia/Riyadh")
        expires_at_saudi = expires_at.astimezone(saudi_tz)

        # Format example: 25 Nov 2025, 09:41 AM
        formatted_saudi_time = expires_at_saudi.strftime("%d %b %Y, %I:%M %p")

        session = QRSession.objects.create(expires_at=expires_at)

        payload = {
            "type": "qr_login",
            "id": str(session.id)
        }

        return Response({
            "qr_payload": payload,
            "expires_at_utc": expires_at,                    # original UTC
            "expires_at_saudi": expires_at_saudi,           # datetime in Riyadh timezone
            "expires_at_formatted": formatted_saudi_time    # nicely formatted string
        })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def approve_qr_session(request):
    session_id = request.data.get("id")

    if not session_id:
        return Response({"detail": "QR session id required."},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        session = QRSession.objects.get(pk=session_id)
    except QRSession.DoesNotExist:
        return Response({"detail": "Invalid QR session."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Expired QR?
    if session.is_expired():
        return Response({"detail": "QR expired."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Already used?
    if session.approved:
        return Response({"detail": "QR already used."},
                        status=status.HTTP_400_BAD_REQUEST)

    user = request.user
    session.mark_approved(user)

    # Tokens
    refresh = RefreshToken.for_user(user)
    access = refresh.access_token

    # Profile picture
    profile = UserProfile.objects.filter(user=user).first()
    profile_pic_url = ""
    if profile and profile.profile_picture:
        profile_pic_url = f"{request.scheme}://{request.get_host()}{profile.profile_picture.url}"

    # Final payload to send through WebSocket
    login_payload = {
        "event": "qr_login_success",
        "data": {
            "refresh": str(refresh),
            "access": str(access),
            "user_id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "phone_number": user.phone_number,
            "level": user.level_id.level if user.level_id else None,
            "employee_id": user.level_id.employee_id if user.level_id else None,
            "profile_picture": profile_pic_url
        }
    }

    # Send over WebSocket
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"qr_{session_id}",
        {
            "type": "qr_login_approved",
            "data": login_payload,
        }
    )

    return Response({"detail": "QR approved successfully."})
