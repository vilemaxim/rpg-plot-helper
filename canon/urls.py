from django.urls import path

from . import views

urlpatterns = [
    path("worlds/<uuid:world_id>/import/", views.import_page, name="canon-import"),
    path("worlds/<uuid:world_id>/<slug:kind>/", views.listing, name="canon-list"),
    path("worlds/<uuid:world_id>/<slug:kind>/<slug:slug>/", views.detail, name="canon-detail"),
]
