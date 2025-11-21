# urls.py
from django.urls import path
from .views import CreateQRSessionAPIView, approve_qr_session

urlpatterns = [
    path("create-qr/", CreateQRSessionAPIView.as_view(), name="qr-create"),
    path('approve-qr/', approve_qr_session.as_view(), name='qr-approve'),
]
