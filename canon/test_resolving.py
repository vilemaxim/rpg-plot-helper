"""Resolving Flags: dismissing one, sending its Mod back to its Mod Writer, and
rejecting the change that raised it. Through web requests, with plotcanon's
sample World and script."""

import plotcanon

from canon.models import Document, Flag
from canon.test_decisions import DecisionTest
from canon.test_reports import STAIR, VIGIL
from organizations.models import Membership
from organizations.tests import sign_in

WARRANT = "a-warrant-for-dunmore"


class ResolvingTest(DecisionTest):
    """After the stair report, the warrant Mod is flagged twice: once for the
    smuggler's death and once for the captain's standing."""

    def setUp(self):
        super().setUp()
        self.flags_page = f"{self.first_world}flags/"
        self.submit(STAIR)

    def flags_on(self, mod, open_only=True):
        with self.in_world():
            flags = Flag.objects.filter(mod__slug=mod)
            if open_only:
                flags = flags.filter(resolution="")
            return list(flags.select_related("change", "resolved_by"))

    def dismiss(self, flag, by=None, back=None):
        return (by or self.mira).post(f"{self.first_world}flags/{flag.pk}/dismiss/",
                                      {"next": back or self.flags_page}, follow=True)

    def send_back(self, mod, reason="The smuggler is dead; rewrite around his partner.",
                  by=None):
        return (by or self.mira).post(f"{self.mod_page(mod)}send-back/", {"reason": reason},
                                      follow=True)

    def warns(self, mod):
        return 'class="warning"' in self.mira.get(self.mod_page(mod)).content.decode()


class Dismissing(ResolvingTest):
    def test_dismissing_a_flag_removes_it_from_the_open_list(self):
        harrow = next(f for f in self.flags_on(WARRANT) if f.change.entity == "harrow-dunmore")

        self.dismiss(harrow)

        page = self.mira.get(self.flags_page).content.decode()
        rows = [r for r in page.split('<tr class="flag">')[1:] if f"mods/{WARRANT}/" in r]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("npcs/harrow-dunmore/", rows[0])

    def test_the_warning_stays_while_any_flag_remains(self):
        first, second = self.flags_on(WARRANT)

        self.dismiss(first)
        self.assertTrue(self.warns(WARRANT))

        self.dismiss(second)
        self.assertFalse(self.warns(WARRANT))

    def test_a_dismissed_flag_stays_on_record_with_who_and_how(self):
        flag = self.flags_on(WARRANT)[0]

        self.dismiss(flag)

        [resolved] = [f for f in self.flags_on(WARRANT, open_only=False) if f.pk == flag.pk]
        self.assertEqual(resolved.resolution, "dismissed")
        self.assertEqual(resolved.resolved_by.email, "mira@example.com")
        self.assertIsNotNone(resolved.resolved_at)
        page = self.mira.get(self.mod_page(WARRANT))
        self.assertContains(page, "Dismissed by mira@example.com")

    def test_the_count_on_the_world_page_goes_down(self):
        with self.in_world():
            before = Flag.objects.open_in(self.world()).count()

        self.dismiss(self.flags_on(WARRANT)[0])

        self.assertContains(self.mira.get(self.first_world), f"{before - 1} open Flags")

    def test_a_flag_is_resolved_once(self):
        flag = self.flags_on(WARRANT)[0]
        self.dismiss(flag)

        response = self.dismiss(flag)

        self.assertContains(response, "already been resolved")

    def test_the_mods_page_offers_dismissing_and_comes_back_to_it(self):
        flag = self.flags_on(WARRANT)[0]
        page = self.mira.get(self.mod_page(WARRANT))
        self.assertContains(page, f"flags/{flag.pk}/dismiss/")

        response = self.dismiss(flag, back=self.mod_page(WARRANT))

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(WARRANT))

    def world(self):
        from organizations.models import World
        return World.objects.get(pk=self.first_world.split("/")[2])


class SendingBack(ResolvingTest):
    def test_sending_a_mod_back_sets_it_to_draft(self):
        self.send_back(WARRANT)

        self.assertEqual(self.state_shown(WARRANT), "Draft")
        stored = self.stored(WARRANT)
        self.assertEqual(stored.fields["state"], "draft")
        self.assertEqual(stored.path, f"inbox/{WARRANT}.md")
        self.assertEqual(stored.fields["canon"], "proposed")

    def test_it_records_why(self):
        self.send_back(WARRANT, reason="Rewrite around his partner.")

        page = self.mira.get(self.mod_page(WARRANT))

        self.assertContains(page, 'class="sent-back warning"', count=1)
        banner = page.content.decode().split('class="sent-back warning"', 1)[1].split("</div>", 1)[0]
        self.assertIn("Sent back to its Mod Writer", banner)
        self.assertIn("Rewrite around his partner.", banner)
        self.assertIn("mira@example.com", banner)

    def test_every_open_flag_on_the_mod_is_resolved_by_it(self):
        self.send_back(WARRANT)

        self.assertEqual(self.flags_on(WARRANT), [])
        self.assertFalse(self.warns(WARRANT))
        for flag in self.flags_on(WARRANT, open_only=False):
            self.assertEqual(flag.resolution, "sent-back")
            self.assertIn("partner", flag.note)

    def test_a_reason_is_needed(self):
        response = self.send_back(WARRANT, reason="   ")

        self.assertContains(response, "Say why")
        self.assertEqual(self.state_shown(WARRANT), "Approved")

    def test_the_mods_file_changes_in_those_values_only(self):
        before = self.stored(WARRANT).text

        self.send_back(WARRANT)

        self.assertEqual(self.stored(WARRANT).text,
                         before.replace("state: approved", "state: draft")
                         .replace("canon: approved", "canon: proposed"))

    def test_a_mod_sent_back_takes_no_reports_until_it_is_approved_again(self):
        self.send_back(WARRANT)

        self.assertNotContains(self.mira.get(self.mod_page(WARRANT)), self.report_form(WARRANT))

    def test_a_mod_that_has_already_been_played_is_not_sent_back(self):
        """Its reports say it has been run; a draft has not. plotcanon would
        warn that the two disagree, so it is refused, as a decision is."""
        response = self.send_back("the-tax-collectors-ledger")

        self.assertContains(response, "has already been played")
        self.assertNotContains(self.mira.get(self.mod_page("the-tax-collectors-ledger")),
                               "send-back/")
        self.assertEqual(self.state_shown("the-tax-collectors-ledger"), "In progress")
        self.assertEqual(len(self.flags_on("the-tax-collectors-ledger")), 1)

    def test_a_reason_has_a_sensible_length(self):
        response = self.send_back(WARRANT, reason="x" * 2001)

        self.assertContains(response, "2,000 characters")
        self.assertEqual(self.state_shown(WARRANT), "Approved")

    def test_a_draft_is_not_sent_back_again(self):
        response = self.send_back("the-guildmasters-daughter")

        self.assertContains(response, "already a draft")

    def test_the_world_stays_one_plotcanon_accepts(self):
        self.send_back(WARRANT)

        with self.in_world():
            files = {d.path: d.text for d in Document.objects.all()}
        self.assertEqual(plotcanon.load_world(files).errors, ())


class RejectingTheChange(ResolvingTest):
    def test_rejecting_a_change_clears_every_flag_it_raised(self):
        death = self.change("harrow-dunmore", "aa-blood-on-the-salt-stair")
        with self.in_world():
            raised = Flag.objects.filter(change=death).count()
        self.assertGreater(raised, 1)

        self.rule(death, "reject")

        with self.in_world():
            self.assertEqual(Flag.objects.filter(change=death, resolution="").count(), 0)
            cleared = Flag.objects.filter(change=death, resolution="change-rejected")
            self.assertEqual(cleared.count(), raised)
            self.assertEqual({f.resolved_by.email for f in cleared}, {"mira@example.com"})

    def test_it_leaves_the_flags_other_changes_raised(self):
        self.rule(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair"), "reject")

        remaining = self.flags_on(WARRANT)

        self.assertEqual([f.change.entity for f in remaining], ["ysolde-marr"])

    def test_approving_a_change_leaves_its_flags_open(self):
        self.rule(self.change("harrow-dunmore", "aa-blood-on-the-salt-stair"), "approve")

        self.assertEqual(len(self.flags_on(WARRANT)), 2)


class WhoMayResolve(ResolvingTest):
    def setUp(self):
        super().setUp()
        self.sam = self.join("sam@example.com")
        self.give("sam@example.com", "mod-writer")
        self.give("sam@example.com", "mod-runner")

    def test_someone_who_is_not_a_plot_master_cannot(self):
        flag = self.flags_on(WARRANT)[0]

        self.assertEqual(self.dismiss(flag, by=self.sam).status_code, 404)
        self.assertEqual(self.send_back(WARRANT, by=self.sam).status_code, 404)
        self.assertEqual(len(self.flags_on(WARRANT)), 2)
        self.assertEqual(self.state_shown(WARRANT), "Approved")

    def test_an_organization_admin_sees_the_warning_and_the_buttons(self):
        # An Organization Admin has every right a Plot Master has.
        with self.in_world():
            Membership.objects.filter(user__email="sam@example.com").update(is_admin=True)
        page = self.sam.get(self.mod_page(WARRANT))

        self.assertContains(page, 'class="warning"')
        self.assertContains(page, "/dismiss/")
        self.assertContains(page, "send-back/")

    def test_a_plot_master_of_another_organization_cannot(self):
        eve = sign_in("eve@example.com")

        self.assertEqual(self.dismiss(self.flags_on(WARRANT)[0], by=eve).status_code, 404)

    def test_it_cannot_be_done_with_a_link(self):
        flag = self.flags_on(WARRANT)[0]

        self.assertEqual(self.mira.get(f"{self.first_world}flags/{flag.pk}/dismiss/").status_code,
                         405)
        self.assertEqual(self.mira.get(f"{self.mod_page(WARRANT)}send-back/").status_code, 405)
