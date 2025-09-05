from django.urls import path
from .views import * 

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='user-registration'),
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('setup-profile/', CreateOrUpdateUserProfileAPIView.as_view(), name='user-profile'),
    path('chat-ui/', chat_ui_view, name='chat-ui'),
    path('profile/', UserProfileAPIView.as_view(), name='user-profile'),
    path('update-profile/', UserProfileUpdateAPIView.as_view(), name='update-user-profile'),
]