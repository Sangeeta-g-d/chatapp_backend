from django.urls import path
from .views import * 

urlpatterns = [
    path("post-feed/", CreateFeedAPIView.as_view(), name="create-feed"),
    path("like/<int:feed_id>/", ToggleFeedLikeAPIView.as_view(), name="toggle-feed-like"),
    path("comment/<int:feed_id>/", AddFeedCommentAPIView.as_view(), name="add-feed-comment"),
    path("latest-feeds/", FeedListAPIView.as_view(), name="latest-feed"),
    path("comments/<int:feed_id>/", FeedCommentsListAPIView.as_view(), name="feed-comments-list"),
]
