from django.urls import path

from . import api, views

app_name = "content"

urlpatterns = [
    path("", views.home, name="home"),
    path("index.html", views.home, name="home_html"),
    path("about.html", views.about, name="about"),
    path("programs.html", views.programs, name="programs"),
    path("contact.html", views.contact, name="contact"),
    path("how-to-pay.html", views.how_to_pay, name="how_to_pay"),
    path("privacy.html", views.privacy, name="privacy"),
    path("terms.html", views.terms, name="terms"),
    path("api/contact", api.contact_submit, name="api_contact"),
    path("pages/<slug:slug>.html", views.dynamic_page, name="page"),
]
