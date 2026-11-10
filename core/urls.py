from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("healthz", views.healthz, name="healthz"),
    path("about/", views.about, name="about"),
    path("robots.txt", views.robots_txt, name="robots"),
    path("favicon.ico", views.favicon, name="favicon"),
]
