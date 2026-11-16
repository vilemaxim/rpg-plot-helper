from django.urls import path

from . import views

urlpatterns = [
    path("worlds/<uuid:world_id>/interview/", views.interview, name="interview"),
    path("worlds/<uuid:world_id>/interview/submit/", views.submit, name="interview-submit"),
]
