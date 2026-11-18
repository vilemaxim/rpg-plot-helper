"""Parallel Groups (ADR-0011), as the plot team sees them: each report's
Group beside it, and plotcanon's warning when two Groups that played side by
side change the same field of the same entity."""

import plotcanon

from accounts.models import User
from canon.models import CanonChange
from canon.storing import files_of
from canon.test_reports import VIGIL, ReportTest
from organizations.models import Membership, Role, World

# The sample's first report on the vigil, played by the Group on the reef.
REEF = VIGIL.text.replace("ran: true\n", "ran: true\ngroup: reef\n", 1)

# Another Group, at the harbour, at the same Event, at the same time.
HARBOUR = """---
id: aa-storm-moon-vigil-harbour
type: after-action
mod: storm-moon-vigil
event: e03-storm-moon
group: harbour
ran: true
finished: false
mod_runner: mira
pcs: [pc-ilse-marrow]
canon_changes:
  - entity: the-tidemother
    kind: narrative
    decision: proposed
    summary: "Was heard singing under the harbour wall."
---

## What Happened

The harbour Group kept watch on the wall.
"""

# The harbour Group, also saying where the smuggler went.
HARBOUR_CLASHING = HARBOUR.replace("""canon_changes:
""", """canon_changes:
  - entity: harrow-dunmore
    kind: status
    decision: proposed
    from: alive
    to: dead
    summary: "Shot on the harbour steps with a lantern in his hand."
""", 1)

# plotcanon's warning on each side of that clash, in its own words.
REEF_WARNED = ("`canon_changes[0]` changes `status` of `harrow-dunmore`, as "
               "`aa-storm-moon-vigil-harbour` does in the Group `harbour`, which played "
               "alongside this one — they are decided in order of report id, so check that "
               "they agree")
HARBOUR_WARNED = ("`canon_changes[0]` changes `status` of `harrow-dunmore`, as "
                  "`aa-storm-moon-vigil` does in the Group `reef`, which played alongside "
                  "this one — they are decided in order of report id, so check that they "
                  "agree")
WARNED = {"aa-storm-moon-vigil": REEF_WARNED, "aa-storm-moon-vigil-harbour": HARBOUR_WARNED}

# The box the warnings are shown in.
CLASH = 'class="warning clashes"'


class GroupTest(ReportTest):
    def file(self, text):
        response = self.mira.post(self.report_form("storm-moon-vigil"), {"text": text},
                                  follow=True)
        self.assertNotContains(response, "errors")
        return response

    def report_page(self, slug, by=None):
        return (by or self.mira).get(f"{self.first_world}reports/{slug}/")


class AReportsGroup(GroupTest):
    def test_the_report_shows_its_group(self):
        self.file(REEF)

        self.assertContains(self.report_page("aa-storm-moon-vigil"),
                            '<p class="group">Group: reef</p>', html=True)

    def test_a_report_with_no_group_shows_none(self):
        self.file(VIGIL.text)

        self.assertNotContains(self.report_page("aa-storm-moon-vigil"), "Group")

    def test_the_mods_list_of_reports_shows_each_ones_group(self):
        self.file(REEF)
        self.file(HARBOUR)

        page = self.mira.get(self.mod_page("storm-moon-vigil"))

        for slug, group in (("aa-storm-moon-vigil", "reef"),
                            ("aa-storm-moon-vigil-harbour", "harbour")):
            with self.subTest(group):
                self.assertContains(page, f'{self.first_world}reports/{slug}/">'
                                          f'Storm Moon Vigil at Storm Moon</a> '
                                          f'<span class="group">(Group: {group})</span>')

    def test_the_pending_page_shows_the_group_beside_each_change(self):
        self.file(REEF)
        self.file(HARBOUR)

        page = self.mira.get(self.pending).content.decode()

        reef = page.split("Stood on the reef until the water covered the crypt door", 1)[1]
        self.assertIn("(Group: reef)", reef.split("</tr>", 1)[0])
        harbour = page.split("Was heard singing under the harbour wall.", 1)[1]
        self.assertIn("(Group: harbour)", harbour.split("</tr>", 1)[0])

    def test_a_pasted_group_is_taken_as_written(self):
        response = self.file(REEF.replace("group: reef", "group: The Reef, north side"))

        self.assertContains(response, "Group: The Reef, north side")
        self.assertIn("group: The Reef, north side\n", self.stored("aa-storm-moon-vigil").text)


class TheClashWarning(GroupTest):
    def test_both_reports_show_the_plot_team_plotcanons_warning(self):
        self.file(REEF)
        self.file(HARBOUR_CLASHING)
        with self.in_world():
            world = World.objects.get(pk=self.first_world.rstrip("/").rsplit("/", 1)[1])
            warnings = plotcanon.load_world(files_of(world)).warnings

        for slug, warned in WARNED.items():
            with self.subTest(slug):
                path = self.stored(slug).path
                self.assertIn(warned, [w.message for w in warnings if w.path == path])
                self.assertContains(self.report_page(slug), warned)

    def test_groups_that_change_different_things_are_not_warned_about(self):
        self.file(REEF)
        self.file(HARBOUR)

        for slug in ("aa-storm-moon-vigil", "aa-storm-moon-vigil-harbour"):
            with self.subTest(slug):
                self.assertNotContains(self.report_page(slug), CLASH)

    def test_once_one_side_is_rejected_there_is_no_clash(self):
        self.file(REEF)
        self.file(HARBOUR_CLASHING)
        with self.in_world():
            change = CanonChange.objects.get(report__slug="aa-storm-moon-vigil-harbour",
                                             entity="harrow-dunmore")
        self.mira.post(f"{self.first_world}changes/{change.pk}/reject/")

        self.assertNotContains(self.report_page("aa-storm-moon-vigil"), CLASH)

    def test_it_is_for_the_plot_team_only(self):
        runner = self.join("rory@example.com")
        self.give("rory@example.com", Role.MOD_RUNNER)
        self.mira.post(f"{self.mod_page('storm-moon-vigil')}assignments/",
                       {"user": User.objects.get(email="rory@example.com").pk, "event": ""})
        self.file(REEF)
        self.file(HARBOUR_CLASHING)

        page = self.report_page("aa-storm-moon-vigil", by=runner)

        self.assertContains(page, "Group: reef")
        self.assertNotContains(page, CLASH)

    def test_an_organization_admin_sees_it(self):
        admin = self.join("ada@example.com")
        with self.in_world():
            Membership.objects.filter(user__email="ada@example.com").update(is_admin=True)
        self.file(REEF)
        self.file(HARBOUR_CLASHING)

        self.assertContains(self.report_page("aa-storm-moon-vigil", by=admin), CLASH)
