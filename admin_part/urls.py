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
    # path("email_center/delete/<int:email_id>/", views.delete_email, name="delete_email"),
    path('user_management/', views.user_management, name='user_management'),
    path('toggle-status/<int:user_id>/', views.toggle_user_status, name='toggle_user_status'),
    path('delete-user/<int:user_id>/', views.delete_user, name='delete_user'),


]