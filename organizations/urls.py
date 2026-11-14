from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("worlds/<uuid:world_id>/", views.world, name="world"),
]
