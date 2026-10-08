from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("catalogue/", include("catalogue.urls")),
    path("orders/", include("orders.urls")),
    path("dispatch/", include("dispatchapp.urls")),
    path("delivery/", include("delivery.urls")),
    path("returns/", include("returnsapp.urls")),
    path("inventory/", include("inventory.urls")),
    path("accounting/app/", include("accounting.urls")),
    path("api/", include("api.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.BASE_DIR / "static")

admin.site.site_header = "Flujo Administration"
admin.site.site_title = "Flujo Admin"
admin.site.index_title = "System Administration"
