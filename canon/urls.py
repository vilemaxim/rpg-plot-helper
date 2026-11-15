from django.urls import path

from . import views

urlpatterns = [
    path("worlds/<uuid:world_id>/import/", views.import_page, name="canon-import"),
    path("worlds/<uuid:world_id>/changes/", views.pending, name="canon-pending"),
    path("worlds/<uuid:world_id>/flags/", views.flags, name="canon-flags"),
    path("worlds/<uuid:world_id>/flags/<int:flag_id>/dismiss/", views.dismiss_flag,
         name="canon-dismiss-flag"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/send-back/", views.send_back,
         name="canon-send-back"),
    path("worlds/<uuid:world_id>/mod-writers/", views.mod_writers, name="canon-mod-writers"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/reassign/", views.reassign,
         name="canon-reassign"),
    path("worlds/<uuid:world_id>/submit-mod/", views.submit_mod, name="canon-submit-mod"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/revise/", views.revise,
         name="canon-revise"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/approve/", views.approve,
         name="canon-approve"),
    path("worlds/<uuid:world_id>/changes/<int:change_id>/<str:decision>/", views.decide,
         name="canon-decide"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/report/", views.report, name="canon-report"),
    path("worlds/<uuid:world_id>/<slug:kind>/", views.listing, name="canon-list"),
    path("worlds/<uuid:world_id>/<slug:kind>/<slug:slug>/", views.detail, name="canon-detail"),
]
