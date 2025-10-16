from django.shortcuts import render
from .models import *
from . serializers import *
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
                    "phone_number": getattr(user, "phone_number", None),
                    "employee_id": getattr(user, "employee_id", None),
                    "level": getattr(user, "level", None),
                }
            }, status=status.HTTP_201_CREATED)

        return Response({
            "status": status.HTTP_400_BAD_REQUEST,
            "message": "Validation error",
            "errors": serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims to token (for client-side decoding if needed)
        token['full_name'] = user.full_name
        token['email'] = user.email
        return token

    def validate(self, attrs):
        data = super().validate(attrs)

        # Add additional user details to response
        data['user_id'] = self.user.id
        data['full_name'] = self.user.full_name
        data['email'] = self.user.email

        # Add level and employee_id if available from EmailCenter
        if self.user.level_id:
            data['level'] = self.user.level_id.level
            data['employee_id'] = self.user.level_id.employee_id
        else:
            data['level'] = None
            data['employee_id'] = None

        return data
    
    
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return Response({
                "status": 401,
                "message": "Invalid credentials",
                "data": None
            }, status=status.HTTP_401_UNAUTHORIZED)

        user = serializer.user

        # ✅ Check if suspended
        if hasattr(user, "is_suspended") and user.is_suspended:
            return Response({
                "status": 403,
                "message": "Your account is suspended. Please contact admin.",
                "data": {
                    "suspension_reason": getattr(user.level_id, "suspension_reason", None),
                    "suspension_until": getattr(user.level_id, "suspension_until", None)
                }
            }, status=status.HTTP_403_FORBIDDEN)

        # ✅ Successful login
        data = serializer.validated_data
        return Response({
            "status": 200,
            "message": "Login successful",
            "data": {
                "refresh": data.get("refresh"),
                "access": data.get("access"),
                "user_id": user.id,
                "full_name": user.full_name,
                "email": user.email,
                "level": getattr(user, "level", None),
                "employee_id": getattr(user, "employee_id", None)
            }
        }, status=status.HTTP_200_OK)
    


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