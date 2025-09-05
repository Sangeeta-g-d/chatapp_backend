from django.shortcuts import render,redirect,get_object_or_404
from django.contrib.auth import authenticate, login,logout
from . models import *
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from .models import EmailCenter
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from feeds.models import Feed
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
    return render(request,'admin_dashboard.html')



def email_center(request):
    emails = EmailCenter.objects.all().order_by('id')
    levels = EmailCenter.objects.values_list("level", flat=True).distinct()

    success = request.GET.get("success")  # ✅ read from query params

    if request.method == "POST":
        if "email_id" in request.POST:  
            # ✅ Update existing email
            email_id = request.POST.get("email_id")
            email_obj = get_object_or_404(EmailCenter, id=email_id)

            email_obj.can_add_story = bool(request.POST.get("can_add_story"))
            email_obj.can_upload_feed = bool(request.POST.get("can_upload_feed"))
            email_obj.can_share_media = bool(request.POST.get("can_share_media"))
            email_obj.can_download_media = bool(request.POST.get("can_download_media"))

            email_obj.is_suspended = bool(request.POST.get("is_suspended"))
            email_obj.suspension_reason = request.POST.get("suspension_reason") or ""
            suspension_until = request.POST.get("suspension_until")
            email_obj.suspension_until = (
                timezone.datetime.fromisoformat(suspension_until) if suspension_until else None
            )

            email_obj.save()
            return redirect(f"{request.path}?success=updated")  # ✅ redirect

        else:  
            # ✅ Add new email
            EmailCenter.objects.create(
                email=request.POST.get("email"),
                employee_id=request.POST.get("employee_id"),
                level=request.POST.get("level"),
                can_add_story=bool(request.POST.get("can_add_story")),
                can_upload_feed=bool(request.POST.get("can_upload_feed")),
                can_share_media=bool(request.POST.get("can_share_media")),
                can_download_media=bool(request.POST.get("can_download_media")),
                is_suspended=bool(request.POST.get("is_suspended")),
                suspension_reason=request.POST.get("suspension_reason") or "",
                suspension_until=(
                    timezone.datetime.fromisoformat(request.POST.get("suspension_until"))
                    if request.POST.get("suspension_until")
                    else None
                ),
            )
            return redirect(f"{request.path}?success=added")  # ✅ redirect

    return render(
        request,
        "email_center.html",
        {"emails": emails, "levels": levels, "success": success},
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