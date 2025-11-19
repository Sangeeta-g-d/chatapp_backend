from django.shortcuts import render,redirect,get_object_or_404,reverse
from django.contrib.auth import authenticate, login,logout
from . models import *
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.contrib import messages
from .models import EmailCenter
from django.http import JsonResponse
from django.db import IntegrityError
from django.core.paginator import Paginator
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from feeds.models import Feed
from feeds.models import Feed, FeedLike, FeedComment
from story.models import StoryModel, StoryView
from django.db.models import Count

# Create your views here.

def index(request):
    return render(request,'index.html')


def login_view(request):
    error_msg = None
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")
        user = authenticate(request, email=email, password=password)

        if user is not None:
            login(request, user)
            request.session.set_expiry(3 * 24 * 60 * 60)
            if user.is_superuser:
                return redirect('/admin_dashboard/')
            else:
                error_msg = "You are not authorized to access this page."
        else:
            error_msg = "Invalid username or password."
    return render(request,'login.html', {'error_msg': error_msg})

def admin_dashboard(request):
    # --- User statistics ---
    total_users = CustomUser.objects.count()
    # Exclude superusers from user counts
    total_users_excluding_superusers = CustomUser.objects.filter(is_superuser=False).count()
    suspended_users = CustomUser.objects.filter(level_id__is_suspended=True, is_superuser=False).count()
    active_users = total_users_excluding_superusers - suspended_users

    # --- Feed statistics ---
    total_feeds = Feed.objects.count()
    total_feed_likes = FeedLike.objects.count()
    total_feed_comments = FeedComment.objects.count()

    # --- Story statistics ---
    total_stories = StoryModel.objects.count()
    active_stories = StoryModel.objects.filter(expires_at__gt=timezone.now()).count()
    expired_stories = total_stories - active_stories
    total_story_views = StoryView.objects.count()

    # --- Top 5 most viewed stories ---
    top_stories = (
        StoryModel.objects.annotate(view_count=Count("views"))
        .order_by("-view_count")[:5]
    )

    context = {
        "total_users": total_users_excluding_superusers,  # Now excludes superusers
        "active_users": active_users,
        "suspended_users": suspended_users,
        "total_feeds": total_feeds,
        "total_feed_likes": total_feed_likes,
        "total_feed_comments": total_feed_comments,
        "total_stories": total_stories,
        "active_stories": active_stories,
        "expired_stories": expired_stories,
        "total_story_views": total_story_views,
        "top_stories": top_stories,
    }
    return render(request, "admin_dashboard.html", context)

@login_required
def user_management(request):
    # Get all users excluding superusers
    users = CustomUser.objects.filter(is_superuser=False).select_related('level_id').order_by('-date_joined')

    # Search functionality
    search_query = request.GET.get('search', '')
    if search_query:
        users = users.filter(
            Q(email__icontains=search_query) |
            Q(full_name__icontains=search_query) |
            Q(phone_number__icontains=search_query) |
            Q(level_id__level__icontains=search_query)
        )

    # Pagination
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Get success status from URL
    success = request.GET.get('success', '')

    context = {
        'users': page_obj,
        'search_query': search_query,
        'total_users': users.count(),
        'success': success,
    }
    return render(request, 'user_management.html', context)


@require_POST
def toggle_user_status(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id, is_superuser=False)
    user.is_active = not user.is_active
    user.save()
    action = "activated" if user.is_active else "deactivated"
    # Redirect with success parameter
    return redirect(f"{reverse('user_management')}?success={action}")


@require_POST
def delete_user(request, user_id):
    user = get_object_or_404(CustomUser, id=user_id, is_superuser=False)
    user.delete()
    # Redirect with success parameter
    return redirect(f"{reverse('user_management')}?success=deleted")

def email_center(request):
    emails = EmailCenter.objects.all().order_by('id')
    levels = EmailCenter.objects.values_list("level", flat=True).distinct()

    toast = None

    if request.method == "POST":
        print("=== POST REQUEST RECEIVED ===")
        print("POST data:", dict(request.POST))
        
        # Check if it's an edit request
        if "email_id" in request.POST and request.POST["email_id"]:
            print("=== EDIT FORM SUBMITTED ===")
            try:
                email_id = request.POST.get("email_id")
                print(f"Editing email ID: {email_id}")
                
                email_obj = get_object_or_404(EmailCenter, id=email_id)

                # Update basic fields
                email_obj.email = request.POST.get("email") or None
                email_obj.phone_number = request.POST.get("phone_number") or None
                email_obj.employee_id = request.POST.get("employee_id")
                email_obj.level = request.POST.get("level")

                # Update permissions
                email_obj.can_add_story = bool(request.POST.get("can_add_story"))
                email_obj.can_upload_feed = bool(request.POST.get("can_upload_feed"))
                email_obj.can_share_media = bool(request.POST.get("can_share_media"))
                email_obj.can_access_web_app = bool(request.POST.get("can_access_web_app"))
                email_obj.can_download_media = bool(request.POST.get("can_download_media"))

                # Update suspension
                email_obj.is_suspended = bool(request.POST.get("is_suspended"))
                email_obj.suspension_reason = request.POST.get("suspension_reason") or ""

                # Handle suspension_until
                suspension_until = request.POST.get("suspension_until")
                if suspension_until:
                    try:
                        email_obj.suspension_until = timezone.datetime.fromisoformat(suspension_until)
                        print(f"Set suspension_until: {email_obj.suspension_until}")
                    except ValueError as e:
                        print(f"Error parsing suspension_until: {e}")
                        email_obj.suspension_until = None
                else:
                    email_obj.suspension_until = None

                # Handle DOB
                dob = request.POST.get("dob")
                email_obj.dob = dob if dob else None

                # Save the object
                email_obj.save()
                print("Email updated successfully!")
                
                toast = {"text": "Email details updated successfully!", "type": "success"}
                
            except Exception as e:
                print(f"Error updating email: {e}")
                toast = {"text": f"Error updating email: {str(e)}", "type": "error"}

        # Check if it's a delete request
        elif "delete_id" in request.POST:
            print("=== DELETE REQUEST ===")
            try:
                delete_id = request.POST.get("delete_id")
                email_obj = get_object_or_404(EmailCenter, id=delete_id)
                email_str = email_obj.email or email_obj.phone_number or f"Employee {email_obj.employee_id}"
                email_obj.delete()
                print(f"Deleted email: {email_str}")
                toast = {"text": f"Email '{email_str}' deleted successfully!", "type": "success"}
            except Exception as e:
                print(f"Error deleting email: {e}")
                toast = {"text": f"Error deleting email: {str(e)}", "type": "error"}

        # Otherwise, it's an add new email request
        else:
            print("=== ADD NEW EMAIL REQUEST ===")
            email = request.POST.get("email")
            phone_number = request.POST.get("phone_number")
            employee_id = request.POST.get("employee_id")
            
            # Validate that at least email or phone number is provided
            if not email and not phone_number:
                toast = {"text": "Please provide at least an email or phone number.", "type": "error"}
            else:
                # Check if email already exists (if provided)
                if email and EmailCenter.objects.filter(email=email).exists():
                    toast = {"text": f"The email '{email}' already exists!", "type": "error"}
                # Check if employee_id already exists
                elif EmailCenter.objects.filter(employee_id=employee_id).exists():
                    toast = {"text": f"Employee ID '{employee_id}' already exists!", "type": "error"}
                else:
                    try:
                        # Handle DOB
                        dob = request.POST.get("dob")
                        
                        # Handle suspension_until
                        suspension_until = request.POST.get("suspension_until")
                        suspension_until_dt = None
                        if suspension_until:
                            try:
                                suspension_until_dt = timezone.datetime.fromisoformat(suspension_until)
                            except ValueError:
                                suspension_until_dt = None

                        EmailCenter.objects.create(
                            email=email or None,
                            employee_id=employee_id,
                            level=request.POST.get("level"),
                            phone_number=phone_number or None,
                            dob=dob if dob else None,
                            can_add_story=bool(request.POST.get("can_add_story")),
                            can_upload_feed=bool(request.POST.get("can_upload_feed")),
                            can_access_web_app=bool(request.POST.get("can_access_web_app")),
                            can_share_media=bool(request.POST.get("can_share_media")),
                            can_download_media=bool(request.POST.get("can_download_media")),
                            is_suspended=bool(request.POST.get("is_suspended")),
                            suspension_reason=request.POST.get("suspension_reason") or "",
                            suspension_until=suspension_until_dt,
                        )
                        print("New email added successfully!")
                        toast = {"text": "New email added successfully!", "type": "success"}
                    except IntegrityError as e:
                        print(f"IntegrityError: {e}")
                        toast = {"text": f"Error adding email: {str(e)}", "type": "error"}
                    except Exception as e:
                        print(f"Error adding email: {e}")
                        toast = {"text": f"Error adding email: {str(e)}", "type": "error"}

        # Refresh the emails list
        emails = EmailCenter.objects.all().order_by('id')
        return render(
            request,
            "email_center.html",
            {"emails": emails, "levels": levels, "toast": toast},
        )

    # GET request - just display the page
    return render(
        request,
        "email_center.html",
        {"emails": emails, "levels": levels},
    )


def feed_view(request):
    level_filter = request.GET.get("level", None)  # ✅ from query params
    feeds = Feed.objects.all().select_related("user", "user__userprofile")
    if level_filter:
        feeds = feeds.filter(user__level_id__level=level_filter)

    # Optional: order by latest
    feeds = feeds.order_by("-created_at")

    levels = EmailCenter.objects.values_list("level", flat=True).distinct()

    # If paginated, wrap in Paginator
    from django.core.paginator import Paginator
    paginator = Paginator(feeds, 30)
    page = request.GET.get("page")
    feeds = paginator.get_page(page)

    return render(request, "feed.html", {
        "feeds": feeds,
        "levels": levels,
        "selected_level": level_filter
    })


@require_POST
def delete_feed(request, feed_id):
    feed = get_object_or_404(Feed, id=feed_id)
    feed.delete()
    return JsonResponse({"success": True})

def logout_view(request):
    logout(request)
    return redirect('login')