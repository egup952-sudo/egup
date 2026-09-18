from django.urls import path

from . import views, admin_views, search_views

app_name = "accounts"

urlpatterns = [
    path("login/", views.dashboard_login, name="dashboard_login"),
    path("logout/", views.dashboard_logout, name="dashboard_logout"),
    path("search/", search_views.admin_search, name="search"),
    path("", views.dashboard_home, name="dashboard_home"),

    path("admins/", admin_views.admin_list, name="admin_list"),
    path("admins/new/", admin_views.admin_create, name="admin_create"),
    path("admins/<int:pk>/edit/", admin_views.admin_edit, name="admin_edit"),
    path("admins/<int:pk>/deactivate/", admin_views.admin_deactivate, name="admin_deactivate"),
]
