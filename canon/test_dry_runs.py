"""Playing a Mod's Dry Run, through web requests, with plotcanon's sample
World. Its Mod "The Bell Beneath" is written in the Dry Run convention."""

import re
from urllib.parse import urljoin

import plotcanon

from canon.models import CanonChange, Document, ModLink
from canon.test_approving import DAUGHTER
from canon.test_mod_submissions import SubmissionTest

BELL = "the-bell-beneath"
BELL_TEXT = plotcanon.sample_world()[f"mods/lanternlight/{BELL}.md"]


def a_bell(slug, **replacing):
    """A new Mod made from The Bell Beneath, under another id."""
    text = BELL_TEXT.replace(f"id: {BELL}", f"id: {slug}") \
        .replace('title: "The Bell Beneath"', f'title: "{slug}"') \
        .replace('aliases: ["The Bell Beneath", "the bell mod"]', f'aliases: ["{slug}"]')
    for old, new in replacing.items():
        text = text.replace(old, new)
    return text


class DryRunTest(SubmissionTest):
    """Mira is Plot Master, Sam writes Mods and Rhea runs them."""

    def dry_run(self, mod=BELL):
        return f"{self.mod_page(mod)}dry-run/"

    def choose(self, page, words, by=None):
        """Follow the choice with these words on a Dry Run page."""
        found = re.search(rf'<a href="([^"]*)">{re.escape(words)}</a>', page.content.decode())
        self.assertIsNotNone(found, f"No choice {words!r}")
        url = found.group(1).replace("&amp;", "&")
        return (by or self.mira).get(urljoin(page.wsgi_request.get_full_path(), url))

    def counts(self):
        with self.in_world():
            return (Document.objects.count(), CanonChange.objects.count(),
                    [d.text for d in Document.objects.order_by("pk")])


class PlayingADryRun(DryRunTest):
    def test_the_mod_page_offers_it(self):
        self.assertContains(self.mira.get(self.mod_page(BELL)), self.dry_run())

    def test_it_starts_at_the_premise_with_the_hooks_as_its_first_choices(self):
        page = self.mira.get(self.dry_run())

        self.assertContains(page, "Premise")
        self.assertContains(page, "The party goes down into the crypt")
        self.assertContains(page, "The sister asks them to close what was opened")
        self.assertContains(page, "?step=The+descent")
        self.assertNotContains(page, "→")

    def test_a_scene_shows_its_text_and_its_exits_as_choices(self):
        page = self.choose(self.mira.get(self.dry_run()),
                           "The sister asks them to close what was opened")

        self.assertContains(page, "<h2>The descent")
        self.assertContains(page, "a stair full of sand and a rope someone left")
        self.assertContains(page, "If players do nothing: the tide gives them an hour")
        self.assertContains(page, ">down the rope</a>")
        self.assertNotContains(page, "[[")

    def test_a_contest_shows_its_results_as_choices(self):
        page = self.mira.get(f"{self.dry_run()}?step=The+bell&step=Who+rings+it")

        self.assertContains(page, ">stop her before the last stroke: win</a>")
        self.assertContains(page, ">stop her before the last stroke: lose</a>")

    def test_an_outcome_is_an_ending_with_ways_to_start_over_or_go_back(self):
        scene = self.mira.get(f"{self.dry_run()}?step=The+bell&step=Who+rings+it")
        page = self.choose(scene, "stop her before the last stroke: win")

        self.assertContains(page, "The crypt goes quiet")
        self.assertContains(page, "Ending")
        self.assertContains(page, '<a href="./">Start over</a>')
        back = self.choose(page, "Back a step")
        self.assertContains(back, "<h2>Who rings it")
        self.assertContains(self.choose(page, "Start over"), "<h2>Premise")

    def test_it_shows_only_story_passages_with_a_link_back_to_the_full_mod(self):
        page = self.mira.get(self.dry_run())

        self.assertContains(page, f'href="{self.mod_page(BELL)}"')
        self.assertNotContains(page, "The sister stays above")    # NPC Casting
        self.assertNotContains(page, "The crypt goes quiet")      # an outcome, not reached

    def test_a_step_that_cannot_be_reached_from_the_one_before_is_not_found(self):
        self.assertEqual(self.mira.get(f"{self.dry_run()}?step=The+bell+is+rung").status_code,
                         404)
        self.assertEqual(self.mira.get(f"{self.dry_run()}?step=Nowhere").status_code, 404)

    def test_playing_it_records_nothing(self):
        before = self.counts()
        page = self.mira.get(self.dry_run())
        page = self.choose(page, "The sister asks them to close what was opened")
        self.choose(page, "down the rope")

        self.assertEqual(self.counts(), before)


class ADryRunThatCannotBeBuilt(DryRunTest):
    def test_a_mod_with_no_structure_says_why_in_words_to_paste(self):
        page = self.mira.get(self.dry_run("storm-moon-vigil"))

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "no Dry Run yet")
        self.assertContains(page, "<pre>Dry Run: ")

    def test_a_link_to_nothing_is_named(self):
        self.submit_mod(a_bell("the-broken-bell", **{"down the rope → [[The bell]]":
                                                     "down the rope → [[The belfry]]"}))

        page = self.sam.get(self.dry_run("the-broken-bell"))

        self.assertContains(page, "no Dry Run yet")
        self.assertContains(page, "The belfry")


    def test_a_part_that_cannot_be_reached_is_named_but_the_rest_plays(self):
        self.submit_mod(a_bell("the-lost-bell", **{"## NPC Casting": (
            "### 4. The loft\n\n**Leads to:** up → [[The bell is taken]]\n\n## NPC Casting")}))

        page = self.sam.get(self.dry_run("the-lost-bell"))

        self.assertContains(page, "cannot be reached")
        self.assertContains(page, "The loft")
        self.assertContains(page, "The sister asks them to close what was opened")


class WhoMayPlayIt(DryRunTest):
    def test_a_mod_writer_may_play_their_draft(self):
        self.submit_mod(a_bell("the-second-bell"))

        self.assertContains(self.sam.get(self.mod_page("the-second-bell")),
                            self.dry_run("the-second-bell"))
        self.assertContains(self.sam.get(self.dry_run("the-second-bell")),
                            "The sister asks them to close what was opened")

    def test_it_is_there_for_a_draft_from_the_inbox_and_a_finished_mod_too(self):
        for mod in (DAUGHTER, "blood-on-the-salt-stair"):
            self.assertEqual(self.mira.get(self.dry_run(mod)).status_code, 200)

    def test_a_mod_runner_may_play_it(self):
        self.assertContains(self.rhea.get(self.dry_run()), "<h2>Premise")

    def test_someone_with_no_role_in_the_world_may_not(self):
        stranger = self.join("stranger@example.com")

        self.assertEqual(stranger.get(self.dry_run()).status_code, 404)

    def test_a_signed_out_person_may_not(self):
        self.assertEqual(self.client.get(self.dry_run()).status_code, 302)


class ThroughAPrivateLink(DryRunTest):
    def setUp(self):
        super().setUp()
        page = self.mira.post(f"{self.mod_page(BELL)}links/", {"label": "Rhea"}, follow=True)
        self.link = re.search(r"http://testserver(/run/[\w-]+/)", page.content.decode()) \
            .group(1)

    def test_the_mod_runner_plays_it_with_no_account(self):
        self.assertContains(self.client.get(self.link), 'href="dry-run/"')
        page = self.client.get(f"{self.link}dry-run/")

        self.assertContains(page, "<h2>Premise")
        page = self.choose(page, "The sister asks them to close what was opened", by=self.client)
        self.assertContains(page, "<h2>The descent")

    def test_it_links_back_to_the_mod_through_the_link_and_nowhere_else_in_the_world(self):
        page = self.client.get(f"{self.link}dry-run/?step=The+descent")

        self.assertContains(page, '<a href="../">Back to the full Mod</a>')
        self.assertNotContains(page, self.first_world)
        self.assertEqual(page["Referrer-Policy"], "no-referrer")

    def test_once_the_link_is_turned_off_it_opens_nothing(self):
        with self.in_world():
            ModLink.objects.update(turned_off_at="2026-01-01T00:00Z")

        self.assertEqual(self.client.get(f"{self.link}dry-run/").status_code, 404)
