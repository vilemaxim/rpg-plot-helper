from django.urls import path

from . import reporting, views

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
    path("worlds/<uuid:world_id>/mods/<slug:slug>/report/interview/", reporting.interview,
         name="report-interview"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/report/interview/walk/", reporting.walk_page,
         name="report-walk"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/report/interview/submit/", reporting.submit,
         name="report-interview-submit"),
    path("worlds/<uuid:world_id>/mods/<slug:slug>/report/interview/start-over/",
         reporting.start_over, name="report-interview-start-over"),
]
