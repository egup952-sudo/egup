from django.urls import path
from . import admin_views

app_name = "media_lib_admin"

urlpatterns = [
    path("gallery/", admin_views.gallery_list, name="gallery"),
    path("gallery/upload/", admin_views.gallery_upload, name="gallery_upload"),
    path("gallery/<int:pk>/delete/", admin_views.gallery_delete, name="gallery_delete"),
    path("gallery/<int:pk>/toggle-publish/", admin_views.gallery_toggle_publish, name="gallery_toggle"),
]
