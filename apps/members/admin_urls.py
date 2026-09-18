from django.urls import path
from . import admin_views, admin_reference_views as ref

app_name = "members_admin"

urlpatterns = [
    path("", admin_views.member_list, name="list"),
    path("new/", admin_views.member_create, name="create"),
    path("export/", admin_views.member_export, name="export"),
    path("<int:pk>/", admin_views.member_detail, name="detail"),

    # Registration reference data (counties/churches/skills/professions/departments)
    path("reference/<str:kind>/", ref.reference_list, name="reference_list"),
    path("reference/<str:kind>/new/", ref.reference_create, name="reference_create"),
    path("reference/<str:kind>/<int:pk>/edit/", ref.reference_edit, name="reference_edit"),
    path("reference/<str:kind>/<int:pk>/delete/", ref.reference_delete, name="reference_delete"),
]
