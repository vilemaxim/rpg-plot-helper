from django.urls import path

from . import views

urlpatterns = [
    path("worlds/<uuid:world_id>/interview/", views.interview, name="interview"),
    path("worlds/<uuid:world_id>/interview/submit/", views.submit, name="interview-submit"),
    path("worlds/<uuid:world_id>/interview/start-over/", views.start_over,
         name="interview-start-over"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/interview/", views.revise_interview,
         name="revise-interview"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/interview/submit/", views.revise_submit,
         name="revise-interview-submit"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/interview/start-over/",
         views.revise_start_over, name="revise-interview-start-over"),
]
