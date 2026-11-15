"""Exchanging a Mod with Twine (ADR-0007): downloading it as a Twee file, and
submitting or revising it from a Twee or Twine 2 HTML file. Through web
requests, with plotcanon's sample World."""

import io
import re
from html import escape

import plotcanon

from canon.test_approving import DAUGHTER
from canon.test_mod_submissions import NEW, SubmissionTest, a_mod
from canon.test_runner_links import VIGIL_MOD, LinkTest


class DownloadingForTwine(SubmissionTest):
    def test_a_reader_of_the_mod_downloads_it_as_twee(self):
        self.submit_mod(a_mod())
        page = self.rhea.get(self.mod_page(NEW))
        self.assertContains(page, f'href="{self.mod_page(NEW)}twee/"')

        response = self.rhea.get(f"{self.mod_page(NEW)}twee/")

        self.assertEqual(response.content.decode(), plotcanon.to_twee(self.stored(NEW).text))
        self.assertIn(f'filename="{NEW}.twee"', response["Content-Disposition"])
        self.assertIn(":: Frontmatter [frontmatter]", response.content.decode())


class DownloadingForTwineThroughALink(LinkTest):
    def test_a_mod_runner_with_a_private_link_downloads_it_as_twee(self):
        link = self.create_link(VIGIL_MOD)
        self.assertContains(self.client.get(link), 'href="twee/"')

        response = self.client.get(f"{link}twee/")

        self.assertEqual(response.content.decode(),
                         plotcanon.to_twee(self.stored(VIGIL_MOD).text))
        self.assertIn(f'filename="{VIGIL_MOD}.twee"', response["Content-Disposition"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")


HEADER = re.compile(r"^:: (.+?)(?: \[(.*?)\])?(?: \{.*\})?$", re.M)


def twine_html(twee):
    """The story in a Twee file as Twine 2 saves it in its library: HTML,
    one `tw-passagedata` per passage."""
    parts = HEADER.split(twee)[1:]
    passages = [(name, tags or "", text.strip("\n"))
                for name, tags, text in zip(parts[::3], parts[1::3], parts[2::3])
                if name not in ("StoryTitle", "StoryData")]
    return ('<tw-storydata name="Debt" startnode="1" format="Harlowe" '
            'format-version="3.3.9" ifid="1D5219C8-DE37-5C40-995D-BE8480D6C3A2">'
            + "".join(f'<tw-passagedata pid="{n}" name="{escape(name)}" tags="{escape(tags)}" '
                      f'position="0,0" size="100,100">{escape(text)}</tw-passagedata>'
                      for n, (name, tags, text) in enumerate(passages, 1))
            + "</tw-storydata>")


def uploaded(text, name):
    upload = io.BytesIO(text.encode() if isinstance(text, str) else text)
    upload.name = name
    return upload


class SubmittingFromTwine(SubmissionTest):
    def test_a_twee_file_is_stored_as_the_mods_markdown(self):
        self.sam.post(self.form, {"file": uploaded(plotcanon.to_twee(a_mod()), f"{NEW}.twee")},
                      follow=True)

        self.assertEqual(self.stored(NEW).text, a_mod())

    def test_a_twine_2_html_file_is_stored_and_its_warnings_are_shown(self):
        macro = a_mod(**{"**Find:** a letter": "(set: $trust to 1) **Find:** a letter"})

        response = self.sam.post(
            self.form, {"file": uploaded(twine_html(plotcanon.to_twee(macro)), "Debt.html")},
            follow=True)

        self.assertEqual(response.redirect_chain[-1][0], self.mod_page(NEW))
        self.assertEqual(self.stored(NEW).text, macro)
        self.assertContains(response, "Twine: passage `The message` has a Twine macro")
        self.assertContains(response, "Converting it from Twine warned about these:")

    def test_a_refused_twine_file_shows_its_warnings_under_the_same_words(self):
        macro = a_mod(slug=DAUGHTER, **{"**Find:** a letter": "(set: $trust to 1) **Find:** a letter"})

        response = self.sam.post(
            self.form, {"file": uploaded(plotcanon.to_twee(macro), f"{DAUGHTER}.twee")})

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "Converting it from Twine warned about these:")
        self.assertContains(response, "Twine: passage `The message` has a Twine macro")

    def test_a_story_with_no_frontmatter_is_refused_showing_why_beside_the_errors(self):
        story = ":: Start\nThe captain waits. [[Knock->The door]]\n\n:: The door\nIt opens.\n"

        response = self.sam.post(self.form, {"file": uploaded(story, "story.twee")})

        self.assertContains(response, "Nothing was saved.")
        self.assertContains(response, "Twine: no passage is tagged `frontmatter`")
        self.assertFalse(self.exists(NEW))

    def test_an_html_file_with_no_twine_story_is_refused_saying_so(self):
        response = self.sam.post(
            self.form, {"file": uploaded("<html><body>Hello</body></html>", "page.html")})

        self.assertContains(response, "page.html cannot be read as a Twine file.")
        self.assertFalse(self.exists(NEW))

    def test_a_published_story_carrying_its_story_formats_code_is_not_too_large(self):
        published = (f"<html><head><script>{'var x = 1;' * 150_000}</script></head><body>"
                     f"{twine_html(plotcanon.to_twee(a_mod()))}</body></html>")
        self.assertGreater(len(published), 1024 * 1024)

        self.sam.post(self.form, {"file": uploaded(published, "Debt.html")})

        self.assertEqual(self.stored(NEW).text, a_mod())

    def test_a_twine_file_over_five_million_bytes_is_refused_as_too_large(self):
        response = self.sam.post(self.form, {"file": uploaded("x" * 5_000_001, "big.twee")})

        self.assertContains(response, "big.twee is too large. The limit is 5 MB.")

    def test_a_twine_file_of_five_million_bytes_is_read_by_plotcanon(self):
        """The app's limit is plotcanon's: a file the app lets through is one
        plotcanon reads, so it is never refused for its size by plotcanon."""
        response = self.sam.post(self.form, {"file": uploaded("x" * 5_000_000, "big.twee")})

        self.assertNotContains(response, "too large")
        self.assertNotContains(response, "larger than")

    def test_a_revision_can_be_a_twee_file(self):
        self.submit_mod(a_mod())
        revised = a_mod(**{"a letter nobody wants": "a sealed letter nobody wants"})

        self.sam.post(f"{self.mod_page(NEW)}revise/",
                      {"file": uploaded(plotcanon.to_twee(revised), f"{NEW}.twee")})

        self.assertEqual(self.stored(NEW).text, revised)


class OtherFilesAreNotTwine(SubmissionTest):
    def test_a_report_named_twee_is_read_as_it_is(self):
        self.submit_mod(a_mod())
        self.approve(NEW, campaign="lanternlight")

        response = self.sam.post(f"{self.mod_page(NEW)}report/",
                                 {"file": uploaded(":: Start\nHello\n", "report.twee")})

        self.assertNotContains(response, "Twine")
