from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("signin/", views.signin, name="signin"),
    path("auth/login", views.login_start, name="login"),
    # Must match the redirect URI registered in Entra exactly (no trailing slash).
    path("auth/callback", views.callback, name="callback"),
    path("signout/", views.signout, name="signout"),
]
