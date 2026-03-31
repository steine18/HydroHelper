from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from django.db import DataError

from sites.models import Site
from water_balance.usgs import USGSAPIError
from .forms import RegistrationForm


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
