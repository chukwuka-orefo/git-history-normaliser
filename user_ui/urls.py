from django.urls import path

from user_ui import views

urlpatterns = [
    path("", views.index, name="index"),
]
