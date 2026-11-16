from django.urls import path

from . import views

urlpatterns = [
    path("worlds/<uuid:world_id>/interview/", views.interview, name="interview"),
    path("worlds/<uuid:world_id>/interview/submit/", views.submit, name="interview-submit"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/interview/", views.revise_interview,
         name="revise-interview"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/interview/submit/", views.revise_submit,
         name="revise-interview-submit"),
]
