from django.urls import path
from .views import * 

urlpatterns = [
    path('upload-story/', UploadStoryAPIView.as_view(), name='upload-story'),
    path('stories/', StoryListAPIView.as_view(), name='story-list'),
    path('mark-view-story/<int:story_id>/', StoryViewRecordAPIView.as_view(), name='story-view'),
    path('delete-story/<int:story_id>/', DeleteStoryAPIView.as_view(), name='delete_story'),
]