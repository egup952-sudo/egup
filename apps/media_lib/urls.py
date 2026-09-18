from django.urls import path
from . import views

app_name = "media_lib"

urlpatterns = [
    path("gallery.html", views.gallery, name="gallery"),
]
