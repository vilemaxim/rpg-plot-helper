"""Organizations and Worlds, tested through web requests, plus the checks the
database makes on its own beneath the app."""

import re

from django.core import mail
from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import include, path

from accounts.models import User
from plothelper import limits
from organizations import tenancy
from organizations.models import Membership, Organization, World, WorldRole


def sign_in(email):
    """A browser signed in as this person, following the emailed link. Each
    call stands for a visit of its own, so the limits on asking for links
    (tested in accounts/tests.py) start over."""
    limits.LimitCount.objects.all().delete()
    client = Client()
    client.post("/sign-in/", {"email": email})
    link = re.search(r"http://testserver(/sign-in/link/\S+)", mail.outbox[-1].body).group(1)
    client.post(link)
    return client


def world_address(client):
    """Where the home page sends this person: their World."""
    response = client.get("/")
    assert response.status_code == 302, response.status_code
    return response["Location"]


@override_settings(OPEN_SIGN_UP=True)
class FirstSignIn(TestCase):
    def test_you_land_on_a_world_of_your_own(self):
        mira = sign_in("mira@example.com")

        response = mira.get("/", follow=True)

        self.assertRegex(response.redirect_chain[-1][0], r"^/worlds/[0-9a-f-]{36}/$")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My first World")
        self.assertContains(response, "My Organization")

    def test_you_are_its_organization_admin_and_plot_master(self):
        mira = sign_in("mira@example.com")

        response = mira.get("/", follow=True)

        self.assertContains(response, "Organization Admin")
        self.assertContains(response, "Plot Master")

    def test_signing_in_again_creates_nothing_new(self):
        first = world_address(sign_in("mira@example.com"))

        second = world_address(sign_in("mira@example.com"))

        self.assertEqual(first, second)
        mira = User.objects.get()
        with tenancy.acting_as(user=mira):
            [membership] = Membership.objects.all()
        with tenancy.acting_as(user=mira, organization=membership.organization_id):
            self.assertEqual(Organization.objects.count(), 1)
            self.assertEqual(World.objects.count(), 1)
            self.assertEqual(WorldRole.objects.count(), 1)

    def test_each_person_gets_their_own_organization(self):
        mira = world_address(sign_in("mira@example.com"))
        sam = world_address(sign_in("sam@example.com"))

        self.assertNotEqual(mira, sam)


@override_settings(OPEN_SIGN_UP=True)
class AnotherOrganizationsWorld(TestCase):
    def setUp(self):
        self.mira = sign_in("mira@example.com")
        self.sam = sign_in("sam@example.com")
        self.miras_world = world_address(self.mira)

    def test_its_member_can_open_it(self):
        self.assertEqual(self.mira.get(self.miras_world).status_code, 200)

    def test_a_member_of_another_organization_gets_not_found(self):
        self.assertEqual(self.sam.get(self.miras_world).status_code, 404)

    def test_a_world_that_does_not_exist_gets_the_same_answer(self):
        response = self.sam.get("/worlds/00000000-0000-4000-8000-000000000000/")

        self.assertEqual(response.status_code, 404)

    def test_a_signed_out_person_is_sent_to_sign_in(self):
        response = Client().get(self.miras_world)

        self.assertRedirects(response, f"/sign-in/?next={self.miras_world}")


def make_a_world_then_fail(request):
    World.objects.create(organization=request.organization, name="Half made")
    raise RuntimeError("the page broke after writing")


urlpatterns = [path("break/", make_a_world_then_fail), path("", include("plothelper.urls"))]


@override_settings(OPEN_SIGN_UP=True, ROOT_URLCONF="organizations.tests")
class WhenAPageFails(TestCase):
    def test_nothing_it_wrote_is_kept(self):
        mira = sign_in("mira@example.com")
        mira.raise_request_exception = False

        response = mira.get("/break/")

        self.assertEqual(response.status_code, 500)
        user = User.objects.get()
        with tenancy.acting_as(user=user):
            organization = Membership.objects.get().organization_id
        with tenancy.acting_as(user=user, organization=organization):
            self.assertEqual([w.name for w in World.objects.all()], ["My first World"])


@override_settings(OPEN_SIGN_UP=True)
class AStaleSession(TestCase):
    def test_a_garbled_organization_in_the_session_is_ignored(self):
        mira = sign_in("mira@example.com")
        session = mira.session
        session["organization_id"] = "not-an-id"
        session.save()

        self.assertEqual(mira.get("/", follow=True).status_code, 200)


@override_settings(OPEN_SIGN_UP=True)
class SigningInOutsideARequestsTransaction(TransactionTestCase):
    def test_it_still_sets_up_the_organization(self):
        """Django's test client and other callers of `login()` do not run
        inside the request transaction."""
        user = User.objects.for_email("mira@example.com")
        client = Client()

        client.force_login(user)

        self.assertEqual(client.get("/", follow=True).status_code, 200)


@override_settings(OPEN_SIGN_UP=True)
class TheDatabaseOnItsOwn(TestCase):
    """Row-level security, checked with no help from the app's own checks."""

    def setUp(self):
        sign_in("mira@example.com")
        sign_in("sam@example.com")
        self.mira = User.objects.get(email="mira@example.com")
        self.sam = User.objects.get(email="sam@example.com")
        with tenancy.acting_as(user=self.mira):
            self.miras_org = Membership.objects.get().organization_id
        with tenancy.acting_as(user=self.sam):
            self.sams_org = Membership.objects.get().organization_id

    def test_with_no_organization_set_a_query_for_worlds_returns_no_rows(self):
        with tenancy.acting_as():
            self.assertEqual(World.objects.count(), 0)
            self.assertEqual(WorldRole.objects.count(), 0)
            self.assertEqual(Membership.objects.count(), 0)
            self.assertEqual(Organization.objects.count(), 0)

    def test_with_an_organization_set_only_its_rows_come_back(self):
        with tenancy.acting_as(organization=self.miras_org):
            [world] = World.objects.all()

        self.assertEqual(world.organization_id, self.miras_org)

    def test_a_person_sees_only_their_own_memberships(self):
        with tenancy.acting_as(user=self.sam):
            self.assertEqual([m.user_id for m in Membership.objects.all()], [self.sam.id])
            self.assertEqual([o.id for o in Organization.objects.all()], [self.sams_org])
            self.assertEqual(World.objects.count(), 0)

    def test_a_row_cannot_be_written_into_another_organization(self):
        with self.assertRaises(ProgrammingError), transaction.atomic():
            with tenancy.acting_as(user=self.sam, organization=self.sams_org):
                World.objects.create(organization_id=self.miras_org, name="Planted")

    def test_a_row_cannot_be_moved_into_another_organization(self):
        with self.assertRaises((ProgrammingError, IntegrityError)), transaction.atomic():
            with tenancy.acting_as(user=self.sam, organization=self.sams_org):
                World.objects.update(organization_id=self.miras_org)

    def test_a_role_cannot_point_at_another_organizations_world(self):
        with tenancy.acting_as(organization=self.miras_org):
            miras_world = World.objects.get()

        with self.assertRaises(IntegrityError), transaction.atomic():
            with tenancy.acting_as(user=self.sam, organization=self.sams_org):
                WorldRole.objects.create(organization_id=self.sams_org, world_id=miras_world.pk,
                                         user=self.sam, role="mod-runner")

    def test_another_organizations_rows_cannot_be_changed_or_deleted(self):
        with tenancy.acting_as(user=self.sam, organization=self.sams_org):
            changed = World.objects.filter(organization_id=self.miras_org).update(name="Defaced")
            deleted, _ = World.objects.filter(organization_id=self.miras_org).delete()

        self.assertEqual((changed, deleted), (0, 0))
        with tenancy.acting_as(organization=self.miras_org):
            self.assertEqual(World.objects.get().name, "My first World")

    def test_the_app_connects_as_a_user_the_rules_apply_to(self):
        """Postgres skips row-level security for superusers and for roles
        marked BYPASSRLS, so the app must be neither."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT rolsuper, rolbypassrls FROM pg_roles "
                           "WHERE rolname = current_user")
            self.assertEqual(cursor.fetchone(), (False, False))


INVITATION_NEEDED = "You need an invitation"


@override_settings(OPEN_SIGN_UP=False)
class SignUpClosed(TestCase):
    """How a self-hosted copy behaves unless it is told otherwise (ADR-0005)."""

    def test_the_first_person_gets_an_organization_and_a_world(self):
        mira = sign_in("mira@example.com")

        response = mira.get("/", follow=True)

        self.assertRegex(response.redirect_chain[-1][0], r"^/worlds/[0-9a-f-]{36}/$")
        self.assertContains(response, "Organization Admin")

    def test_a_second_new_person_gets_none_and_is_told_they_need_an_invitation(self):
        sign_in("mira@example.com")
        sam = sign_in("sam@example.com")

        response = sam.get("/")

        self.assertContains(response, INVITATION_NEEDED)
        self.assertNotContains(response, "My Organization")

    def test_a_person_without_an_organization_cannot_open_anyones_world(self):
        miras_world = world_address(sign_in("mira@example.com"))
        sam = sign_in("sam@example.com")

        self.assertEqual(sam.get(miras_world).status_code, 404)

    def test_someone_who_already_belongs_signs_in_as_before(self):
        first = world_address(sign_in("mira@example.com"))
        sign_in("sam@example.com")

        again = sign_in("mira@example.com")

        self.assertEqual(world_address(again), first)

    def test_asking_for_a_link_and_never_using_it_does_not_take_the_first_place(self):
        Client().post("/sign-in/", {"email": "stranger@example.com"})

        mira = sign_in("mira@example.com")

        self.assertNotContains(mira.get("/", follow=True), INVITATION_NEEDED)

    def organization_of(self, email):
        user = User.objects.get(email=email)
        with tenancy.acting_as(user=user):
            return user, Membership.objects.get().organization_id

    def test_if_the_organization_is_deleted_the_next_person_can_start_again(self):
        """Nobody is locked out for good, however many people have signed in."""
        sign_in("mira@example.com")
        sign_in("sam@example.com")
        mira, organization = self.organization_of("mira@example.com")
        with tenancy.acting_as(user=mira, organization=organization):
            Organization.objects.all().delete()

        sam = sign_in("sam@example.com")

        self.assertNotContains(sam.get("/", follow=True), INVITATION_NEEDED)

    def test_the_organization_outlives_the_person_who_created_it(self):
        """With its first person gone, the Organization is still the one
        Organization, and a stranger does not get another."""
        sign_in("mira@example.com")
        mira, organization = self.organization_of("mira@example.com")
        with tenancy.acting_as(user=mira, organization=organization):
            mira.delete()

        sam = sign_in("sam@example.com")

        self.assertContains(sam.get("/"), INVITATION_NEEDED)

    def test_signing_in_again_does_not_earn_an_organization(self):
        sign_in("mira@example.com")
        sign_in("sam@example.com")

        sam = sign_in("sam@example.com")

        self.assertContains(sam.get("/"), INVITATION_NEEDED)


@override_settings(OPEN_SIGN_UP=True)
class SignUpOpen(TestCase):
    """How a public host behaves: everyone who signs up gets their own."""

    def test_every_new_person_gets_their_own_organization_and_world(self):
        mira = world_address(sign_in("mira@example.com"))
        sam = world_address(sign_in("sam@example.com"))

        self.assertRegex(mira, r"^/worlds/[0-9a-f-]{36}/$")
        self.assertRegex(sam, r"^/worlds/[0-9a-f-]{36}/$")
        self.assertNotEqual(mira, sam)


class TheSetting(TestCase):
    def read(self, module, environment):
        import importlib
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, environment, clear=False):
            for name in set(os.environ) & {"OPEN_SIGN_UP"} - set(environment):
                del os.environ[name]
            return importlib.reload(importlib.import_module(module)).OPEN_SIGN_UP

    def test_it_is_off_unless_turned_on(self):
        self.assertIs(self.read("plothelper.settings.base", {}), False)

    def test_the_environment_turns_it_on(self):
        self.assertIs(self.read("plothelper.settings.base", {"OPEN_SIGN_UP": "true"}), True)
        self.assertIs(self.read("plothelper.settings.base", {"OPEN_SIGN_UP": "1"}), True)

    def test_anything_else_leaves_it_off(self):
        self.assertIs(self.read("plothelper.settings.base", {"OPEN_SIGN_UP": "false"}), False)
        self.assertIs(self.read("plothelper.settings.base", {"OPEN_SIGN_UP": ""}), False)

    def test_local_development_has_it_on(self):
        self.assertIs(self.read("plothelper.settings.local", {}), True)

    def test_local_development_can_turn_it_off_to_try_a_self_hosted_copy(self):
        self.assertIs(self.read("plothelper.settings.local", {"OPEN_SIGN_UP": "false"}), False)


@override_settings(OPEN_SIGN_UP=False)
class EmptyingTheDatabase(TransactionTestCase):
    """`manage.py flush` and the like empty tables with TRUNCATE, which removes
    rows without deleting them one by one. The count of Organizations has to
    notice, or a closed copy would think its one Organization still exists."""

    def test_the_next_person_can_start_again(self):
        sign_in("mira@example.com")
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE organizations_organization CASCADE")

        sam = sign_in("sam@example.com")

        self.assertNotContains(sam.get("/", follow=True), INVITATION_NEEDED)
