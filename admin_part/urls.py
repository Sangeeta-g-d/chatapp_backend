from django.urls import path
from . import views

urlpatterns = [
    # path('',views.index,name="index"),
    path('',views.login_view,name="login"),
    path('admin_dashboard/',views.admin_dashboard,name="admin_dashboard"),
    path('email_center/',views.email_center,name="email_center"),
    path('feed/',views.feed_view,name="feed"),
    path('logout/',views.logout_view,name="logout"),
    path("feeds/delete/<int:feed_id>/", views.delete_feed, name="delete_feed"),
]