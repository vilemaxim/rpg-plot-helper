from django.urls import include, path

urlpatterns = [
    path("", include("organizations.urls")),
    path("", include("accounts.urls")),
    path("", include("interviews.urls")),
    path("", include("canon.urls")),
]
