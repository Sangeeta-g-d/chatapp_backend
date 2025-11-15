# chat/routing.py
from django.urls import path
from .consumers import ChatConsumer,QRLoginConsumer
from django.urls import re_path
from story.consumers import StoryConsumer

websocket_urlpatterns = [
    path("ws/chat/<int:chat_group_id>/", ChatConsumer.as_asgi()),
    path("ws/qr/<uuid:session_id>/", QRLoginConsumer.as_asgi()),

    # story consumer 
    re_path(r'ws/stories/$', StoryConsumer.as_asgi()),
]
