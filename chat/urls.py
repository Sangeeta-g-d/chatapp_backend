from django.urls import path
from .views import * 

urlpatterns = [
    path('new-chat/', OtherUsersProfileAPIView.as_view(), name='other-users'),
    path('open-chat/', ChatHistoryAPIView.as_view(), name='chat-history'),
    path('create-group/', CreateGroupChatAPIView.as_view(), name='create-group-chat'),
    path('chats/', CombinedChatOverviewAPIView.as_view(), name='chat-list'),
   
    path('mark-seen/', mark_message_seen, name='mark-message-seen'),
    path('add-reaction/', add_reaction_to_message, name='add-reaction-to-message'),

    path('toggle-pin-chat/<int:chat_group_id>/', TogglePinChatAPIView.as_view(), name='pinned-chats'),
    path('add-group-member/<int:group_id>/', AddGroupMembersAPIView.as_view(), name='add-members-to-group-chat'),
    path('group-info/<int:group_id>/', ChatGroupDetailAPIView.as_view(), name='group-info'),

    # media
    path('upload-media/', MediaMessageUploadAPIView.as_view(), name='upload-chat-media'),
    path('delete-message/<message_id>/', DeleteMessageAPIView.as_view(), name='delete-message'),

  
]