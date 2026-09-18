from django.urls import path
from . import admin_views, admin_pages_views as pages

app_name = "content_admin"

urlpatterns = [
    path("hero/", admin_views.hero_list, name="hero_list"),
    path("hero/new/", admin_views.hero_create, name="hero_create"),
    path("hero/<int:pk>/edit/", admin_views.hero_edit, name="hero_edit"),
    path("hero/<int:pk>/delete/", admin_views.hero_delete, name="hero_delete"),
    path("settings/", admin_views.site_settings, name="site_settings"),

    path("social-links/", admin_views.social_link_list, name="social_link_list"),
    path("social-links/new/", admin_views.social_link_create, name="social_link_create"),
    path("social-links/<int:pk>/edit/", admin_views.social_link_edit, name="social_link_edit"),
    path("social-links/<int:pk>/delete/", admin_views.social_link_delete, name="social_link_delete"),

    path("messages/", admin_views.message_list, name="message_list"),
    path("messages/<int:pk>/toggle-read/", admin_views.message_toggle_read, name="message_toggle_read"),

    path("pages/", pages.page_list, name="page_list"),
    path("pages/new/", pages.page_create, name="page_create"),
    path("pages/<int:pk>/edit/", pages.page_edit, name="page_edit"),
    path("pages/<int:pk>/toggle-publish/", pages.page_toggle_publish, name="page_toggle_publish"),
    path("pages/<int:pk>/delete/", pages.page_delete, name="page_delete"),
]
