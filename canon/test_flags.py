"""Flags: a proposed Canon Change warns every unfinished Mod that features what
it changes. Through web requests, with plotcanon's sample World and script."""

import plotcanon

from accounts.models import User
from canon.models import Flag
from canon.test_reports import KEEPER, LEDGER_2, STAIR, VIGIL, VIGIL_2, ReportTest
from organizations import tenancy
from organizations.models import Membership
from organizations.tests import sign_in


class FlagTest(ReportTest):
    def setUp(self):
        super().setUp()
        self.flags_page = f"{self.first_world}flags/"

    def flagged(self):
        """The ids of the Mods with an open Flag, each once."""
        with self.in_world():
            return sorted(set(Flag.objects.values_list("mod__slug", flat=True)))

    def flags_from(self, scripted):
        """The ids of the Mods flagged by one report, each once."""
        report = scripted.path.rsplit("/", 1)[-1].removesuffix(".md")
        with self.in_world():
            return sorted(set(Flag.objects.filter(change__report__slug=report)
                              .values_list("mod__slug", flat=True)))


class Raising(FlagTest):
    def test_each_scripted_report_raises_exactly_the_flags_it_is_expected_to(self):
        for scripted in plotcanon.sample_script():
            with self.subTest(scripted.path):
                self.submit(scripted)
                self.assertEqual(self.flags_from(scripted), sorted(scripted.flags))

    def test_a_change_in_one_campaign_flags_a_mod_in_another(self):
        """The ledger runs in Tideward. The warrant for the smuggler is a
        Lanternlight Mod, and it features him."""
        self.submit(LEDGER_2)

        self.assertIn("a-warrant-for-dunmore", self.flags_from(LEDGER_2))
        self.assertEqual(self.stored("a-warrant-for-dunmore").fields["campaign"], "lanternlight")

    def test_finished_and_shelved_mods_are_never_flagged(self):
        """The captain is featured by a finished Mod and a shelved one."""
        self.submit(STAIR)

        flagged = self.flagged()
        for mod in ("the-low-tide-market", "the-wardens-ball"):
            self.assertEqual(self.stored(mod).fields["state"] in ("finished", "shelved"), True)
            self.assertNotIn(mod, flagged)

    def test_a_mod_finished_by_the_report_is_not_flagged_by_it(self):
        self.submit(STAIR)

        self.assertNotIn("blood-on-the-salt-stair", self.flags_from(STAIR))

    def test_a_report_that_touches_nothing_unfinished_raises_none(self):
        self.submit(VIGIL)

        self.submit(VIGIL_2)

        self.assertEqual(self.flags_from(VIGIL_2), [])

    def test_nothing_is_flagged_by_the_import(self):
        """The imported reports' changes were already decided."""
        self.assertEqual(self.flagged(), [])

    def test_a_refused_report_raises_nothing(self):
        self.submit(STAIR, text=STAIR.text.replace("mod_runner: dev\n", ""))

        self.assertEqual(self.flagged(), [])


class WhatAFlagSays(FlagTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)

    def test_the_world_has_a_page_listing_open_flags(self):
        response = self.mira.get(self.flags_page)

        self.assertEqual(response.status_code, 200)
        for mod in STAIR.flags:
            self.assertContains(response, f'href="{self.first_world}mods/{mod}/"')

    def test_a_flag_names_the_change_the_feature_and_the_report(self):
        page = self.mira.get(self.flags_page).content.decode()
        row = next(r for r in page.split("<tr>") if "mods/a-warrant-for-dunmore/" in r)

        self.assertIn(f'href="{self.first_world}npcs/harrow-dunmore/"', row)
        self.assertIn("Went over the edge at the third landing", row)
        self.assertIn(f'href="{self.first_world}reports/aa-blood-on-the-salt-stair/"', row)
        self.assertIn("Status", row)

    def test_each_mod_change_pair_is_one_row(self):
        page = self.mira.get(self.flags_page).content.decode()

        with self.in_world():
            self.assertEqual(page.count('<tr class="flag">'), Flag.objects.count())

    def test_the_world_page_says_how_many_are_open(self):
        with self.in_world():
            count = Flag.objects.count()

        page = self.mira.get(self.first_world)

        self.assertContains(page, self.flags_page)
        self.assertContains(page, f"{count} open Flags")

    def test_a_flagged_mods_page_shows_a_warning(self):
        page = self.mira.get(self.mod_page("a-warrant-for-dunmore"))

        self.assertContains(page, 'class="warning"')
        self.assertContains(page, "Harrow Dunmore")
        self.assertContains(page, "Went over the edge at the third landing")
        self.assertContains(page, f"{self.first_world}reports/aa-blood-on-the-salt-stair/")

    def test_a_mod_with_no_flags_shows_no_warning(self):
        self.assertNotContains(self.mira.get(self.mod_page("the-bell-beneath")), 'class="warning"')

    def test_with_no_flags_the_page_says_so(self):
        eve = sign_in("eve@example.com")
        eves_world = eve.get("/", follow=True).redirect_chain[-1][0]

        self.assertContains(eve.get(f"{eves_world}flags/"), "No Mods are flagged")


class WhoSeesThem(FlagTest):
    def setUp(self):
        super().setUp()
        self.submit(STAIR)
        self.sam = self.join("sam@example.com")

    def test_a_mod_runner_sees_the_warning_on_the_mod_they_run(self):
        self.give("sam@example.com", "mod-runner")

        self.assertContains(self.sam.get(self.mod_page("a-warrant-for-dunmore")), 'class="warning"')
        self.assertEqual(self.sam.get(self.flags_page).status_code, 200)

    def test_someone_with_no_role_in_the_world_cannot(self):
        self.assertEqual(self.sam.get(self.flags_page).status_code, 404)
        self.assertEqual(sign_in("eve@example.com").get(self.flags_page).status_code, 404)


class TheDatabaseOnItsOwn(FlagTest):
    def test_with_no_organization_set_a_query_for_flags_returns_no_rows(self):
        self.submit(STAIR)

        with tenancy.acting_as():
            self.assertEqual(Flag.objects.count(), 0)

    def test_another_organization_sees_none_of_them(self):
        self.submit(STAIR)
        sign_in("eve@example.com")
        eve = User.objects.get(email="eve@example.com")
        with tenancy.acting_as(user=eve):
            organization = Membership.objects.get().organization_id

        with tenancy.acting_as(user=eve, organization=organization):
            self.assertEqual(Flag.objects.count(), 0)
