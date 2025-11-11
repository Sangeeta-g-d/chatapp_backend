from django.shortcuts import render
from .models import *
from .serializers import *
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from admin_part.models import CustomUser
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from chatapp_backend.mixins import StandardResponseMixin
# Create your views here.

def chat_ui_view(request):
    return render(request, 'chat/chat_g.html')


class StandardAuthAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        # ✅ Suspension check before calling the view
        if (
            request.user 
            and request.user.is_authenticated 
            and getattr(request.user, "is_suspended", False)
        ):
            return Response(
                {
                    "status": 403,
                    "message": "Your account is suspended.",
                    "data": {
                        "suspension_reason": getattr(request.user.level_id, "suspension_reason", None),
                        "suspension_until": getattr(request.user.level_id, "suspension_until", None),
                    },
                },
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)

class UserRegistrationView(APIView):
    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                "status": status.HTTP_201_CREATED,
                "message": "User registered successfully",
                "data": {
                    "user_id": user.id,
                    "full_name": user.full_name,
                    "email": user.email,
                    "phone_number": user.phone_number,
                    "level": getattr(user.level_id, "level", None),
                    "employee_id": getattr(user.level_id, "employee_id", None),
                    "permissions": {
                        "can_add_story": user.can_add_story,
                        "can_upload_feed": user.can_upload_feed,
                        "can_share_media": user.can_share_media,
                        "can_download_media": user.can_download_media,
                    }
                }
            }, status=status.HTTP_201_CREATED)

        # Convert validation errors to readable string or dict
        error_messages = serializer.errors
        # Optional: Flatten single error messages
        if isinstance(error_messages, dict):
            flat_errors = []
            for field, errors in error_messages.items():
                flat_errors.append(f"{field}: {', '.join(errors)}")
            error_messages = " | ".join(flat_errors)

        return Response({
            "status": status.HTTP_400_BAD_REQUEST,
            "message": error_messages
        }, status=status.HTTP_400_BAD_REQUEST)


class CustomTokenObtainPairView(APIView):
    serializer_class = CustomLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']

        # Check suspension (if using EmailCenter)
        if hasattr(user, 'is_suspended') and user.is_suspended:
            return Response({
                "status": 403,
                "message": "Your account is suspended. Please contact admin.",
                "data": {
                    "suspension_reason": getattr(user.level_id, 'suspension_reason', None),
                    "suspension_until": getattr(user.level_id, 'suspension_until', None)
                }
            }, status=status.HTTP_403_FORBIDDEN)

        # Generate tokens
        refresh = RefreshToken.for_user(user)
        access = refresh.access_token

        return Response({
            "status": 200,
            "message": "Login successful",
            "data": {
                "refresh": str(refresh),
                "access": str(access),
                "user_id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "phone_number": user.phone_number,
                "level": user.level_id.level if user.level_id else None,
                "employee_id": user.level_id.employee_id if user.level_id else None
            }
        })


class SendOTPView(APIView):
    def post(self, request):
        email = request.data.get("email")

        # check if user exists & suspended
        try:
            user = CustomUser.objects.get(email=email)
            if user.is_suspended:
                return Response(
                    {"message": "Your account is suspended."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except CustomUser.DoesNotExist:
            pass  # No user yet, allow OTP creation

        serializer = SendOTPSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"message": "OTP sent to your email"}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyOTPView(APIView):
    def post(self, request):
        email = request.data.get("email")

        # check suspension again before verifying
        try:
            user = CustomUser.objects.get(email=email)
            if user.is_suspended:
                return Response(
                    {"message": "Your account is suspended."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        except CustomUser.DoesNotExist:
            pass

        serializer = VerifyOTPSerializer(data=request.data)
        if serializer.is_valid():
            result = serializer.save()
            return Response(result, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class CreateOrUpdateUserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            profile, created = UserProfile.objects.get_or_create(user=request.user)

            serializer = UserProfileBasicSerializer(
                instance=profile,
                data=request.data,
                partial=True
            )

            if serializer.is_valid():
                serializer.save()
                return Response({
                    "success": True,
                    "message": "Profile created successfully" if created else "Profile updated successfully",
                    "data": serializer.data
                }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

            return Response({
                "success": False,
                "message": "Validation failed",
                "errors": serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "success": False,
                "message": "Internal server error",
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class UserProfileAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if user and user.is_authenticated and getattr(user, 'is_suspended', False):
            return Response(
                {
                    "status": 403,
                    "message": "Your account is suspended.",
                    "data": {
                        "suspension_reason": getattr(user.level_id, "suspension_reason", None),
                        "suspension_until": getattr(user.level_id, "suspension_until", None),
                    },
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            profile = UserProfile.objects.get(user=user)
            serializer = UserProfileDetailSerializer(profile, context={'request': request})
            return Response(serializer.data)
        except UserProfile.DoesNotExist:
            return Response({"error": "User profile not found."}, status=404)


class UserProfileUpdateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileUpdateSerializer(profile)
        return Response(serializer.data)

    def put(self, request):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        serializer = UserProfileUpdateSerializer(profile, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class RegisterDeviceTokenAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        device_token = request.data.get("device_token")

        if not device_token:
            return Response(
                {"success": False, "message": "Device token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Update if exists, otherwise create
        device, created = UserDevice.objects.update_or_create(
            device_token=device_token,
            defaults={"user": request.user},
        )

        return Response(
            {
                "success": True,
                "message": "Device token registered successfully",
                "data": {
                    "device_token": device.device_token,
                    "user_id": request.user.id,
                    "is_new": created,
                },
            },
            status=status.HTTP_200_OK,
        )



# phone OTP
# -------- Send OTP -------- #
class SendPhoneOTPAPIView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = SendPhoneOTPSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'status': 'success',
                'message': 'OTP sent successfully.'
            }, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifyPhoneOTPAPIView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = VerifyPhoneOTPSerializer(data=request.data)
        if serializer.is_valid():
            result = serializer.save()
            user = result['user']

            refresh = RefreshToken.for_user(user)

            return Response({
                "status": status.HTTP_200_OK,
                "message": result.get("message", "Login successful"),
                "data": {
                    "refresh": str(refresh),
                    "access": str(refresh.access_token),
                    "user_id": user.id,
                    "full_name": user.full_name,
                    "email": user.email,
                    "level": getattr(user, "level", None),
                    "employee_id": getattr(user, "employee_id", None)
                }
            }, status=status.HTTP_200_OK)

        return Response({
            "status": status.HTTP_400_BAD_REQUEST,
            "message": "Invalid OTP",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)