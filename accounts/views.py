from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from django.db import DataError

from sites.models import Site
from water_balance.usgs import USGSAPIError
from .forms import RegistrationForm

User = get_user_model()


def register(request):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def account(request):
    return render(request, "accounts/account.html")


@login_required
def add_site(request):
    if not request.user.is_superuser:
        return redirect("account")

    result = None
    site = None
    error_msg = None
    site_no = ""

    if request.method == "POST":
        site_no = request.POST.get("site_no", "").strip()
        if site_no:
            if Site.objects.filter(site_no=site_no).exists():
                site = Site.objects.get(site_no=site_no)
                result = "exists"
            else:
                try:
                    site = Site.get_or_fetch(site_no)
                    if not site.name:
                        site.delete()
                        site = None
                        result = "not_found"
                    else:
                        result = "added"
                except (USGSAPIError, DataError) as exc:
                    error_msg = str(exc)
                    result = "error"

    return render(request, "accounts/add_site.html", {
        "result": result,
        "site": site,
        "error_msg": error_msg,
        "site_no": site_no,
    })


@login_required
def manage_users(request):
    if not request.user.is_staff:
        return redirect('home')
    users = User.objects.exclude(is_superuser=True).order_by('username')
    return render(request, 'accounts/manage_users.html', {'users': users})


@login_required
@require_POST
def set_user_tier(request, pk):
    if not request.user.is_staff:
        return JsonResponse({'ok': False}, status=403)
    user = get_object_or_404(User, pk=pk)
    if user.is_superuser:
        return JsonResponse({'ok': False}, status=403)
    tier = request.POST.get('tier')
    if tier not in (User.TIER_BASIC, User.TIER_ADVANCED):
        return JsonResponse({'ok': False, 'error': 'Invalid tier'}, status=400)
    user.tier = tier
    user.save(update_fields=['tier'])
    return JsonResponse({'ok': True, 'tier': user.tier})
