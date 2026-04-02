from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("account/", views.account, name="account"),
    path("admin-tools/add-site/", views.add_site, name="add_site"),
    path("admin-tools/users/", views.manage_users, name="manage_users"),
    path("admin-tools/users/<int:pk>/set-tier/", views.set_user_tier, name="set_user_tier"),
]
