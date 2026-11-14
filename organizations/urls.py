from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("worlds/<uuid:world_id>/", views.world, name="world"),
    path("worlds/<uuid:world_id>/rename/", views.rename_world, name="rename-world"),
    path("worlds/<uuid:world_id>/people/", views.people, name="world-people"),
    path("worlds/<uuid:world_id>/roles/", views.give_role, name="give-role"),
    path("worlds/<uuid:world_id>/roles/remove/", views.remove_role, name="remove-role"),
    path("organization/", views.organization, name="organization"),
    path("organization/name/", views.rename_organization, name="rename-organization"),
    path("organization/worlds/", views.create_world, name="create-world"),
    path("organization/invitations/", views.invite, name="invite"),
    path("organization/switch/", views.switch_organization, name="switch-organization"),
    path("organization/leave/", views.leave_organization, name="leave-organization"),
    path("invitations/", views.invitations, name="invitations"),
    path("invitations/<int:invitation_id>/accept/", views.accept_invitation,
         name="accept-invitation"),
    path("invitations/<int:invitation_id>/decline/", views.decline_invitation,
         name="decline-invitation"),
]
