from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from .sitemaps import sitemaps

admin_prefix = settings.ADMIN_ROUTE_PREFIX.strip('/')

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),

    # Platform admin dashboard — discreet path (brief section 22). Real
    # protection is auth+RBAC (apps.accounts.permissions), not obscurity.
    path(f'{admin_prefix}/', include('apps.accounts.urls')),
    path(f'{admin_prefix}/members/', include('apps.members.admin_urls')),
    path(f'{admin_prefix}/payments/', include('apps.payments.admin_urls')),
    path(f'{admin_prefix}/events/', include('apps.events.admin_urls')),
    path(f'{admin_prefix}/announcements/', include('apps.announcements.admin_urls')),
    path(f'{admin_prefix}/media/', include('apps.media_lib.admin_urls')),
    path(f'{admin_prefix}/content/', include('apps.content.admin_urls')),
    path(f'{admin_prefix}/audit/', include('apps.audit.admin_urls')),

    path('payments/', include('apps.payments.urls')),

    # Original frontend's exact filenames/paths — preserved so every
    # existing internal link keeps working unchanged.
    path('', include('apps.content.urls')),
    path('', include('apps.members.urls')),
    path('', include('apps.events.urls')),
    path('', include('apps.announcements.urls')),
    path('', include('apps.media_lib.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
