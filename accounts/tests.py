"""Signing in, tested the way a person does it: request pages, submit the form,
read the email, follow the link."""

import re

from django.core import mail
from django.test import TestCase, override_settings

from accounts.models import User

SIGN_IN = "/sign-in/"


class SignInTest(TestCase):
    def ask_for_a_link(self, email, **extra):
        return self.client.post(SIGN_IN, {"email": email, **extra})

    def link_from_the_email(self):
        """The sign-in link in the most recent email, as a path the test client can use."""
        body = mail.outbox[-1].body
        match = re.search(r"http://testserver(/sign-in/link/\S+)", body)
        self.assertIsNotNone(match, body)
        return match.group(1)

    def sign_in(self, email="mira@example.com"):
        self.ask_for_a_link(email)
        return self.client.post(self.link_from_the_email())

    def assert_signed_out(self):
        self.assertRedirects(self.client.get("/"), "/sign-in/?next=/")


class SignedOut(SignInTest):
    def test_the_home_page_sends_you_to_sign_in(self):
        response = self.client.get("/")

        self.assertRedirects(response, "/sign-in/?next=/")

    def test_any_other_page_sends_you_to_sign_in(self):
        response = self.client.get("/worlds/the-moon/")

        self.assertRedirects(response, "/sign-in/?next=/worlds/the-moon/",
                             fetch_redirect_response=False)

    def test_the_sign_in_page_asks_for_an_email(self):
        response = self.client.get(SIGN_IN)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="email"')
        self.assertNotContains(response, 'type="password"')


class AskingForALink(SignInTest):
    def test_a_link_is_emailed_to_the_address_given(self):
        response = self.ask_for_a_link("mira@example.com")

        self.assertContains(response, "Check your email")
        self.assertContains(response, "mira@example.com")
        [message] = mail.outbox
        self.assertEqual(message.to, ["mira@example.com"])
        self.assertIn("http://testserver/sign-in/link/", message.body)

    def test_asking_does_not_sign_you_in(self):
        self.ask_for_a_link("mira@example.com")

        self.assert_signed_out()

    def test_something_that_is_not_an_email_is_refused(self):
        response = self.ask_for_a_link("mira at example")

        self.assertContains(response, "Enter a valid email address")
        self.assertEqual(mail.outbox, [])
        self.assertEqual(User.objects.count(), 0)

    def test_a_new_address_gets_an_account(self):
        self.ask_for_a_link("mira@example.com")

        self.assertEqual([u.email for u in User.objects.all()], ["mira@example.com"])

    def test_the_same_address_in_different_case_is_one_account(self):
        self.ask_for_a_link("mira@example.com")
        self.ask_for_a_link(" Mira@Example.COM ")

        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_the_database_itself_refuses_a_second_account_for_one_address(self):
        from django.db import IntegrityError, transaction

        self.ask_for_a_link("mira@example.com")

        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(email="Mira@Example.com")

    def test_an_address_to_another_site_is_never_put_in_the_email(self):
        self.ask_for_a_link("mira@example.com", next="https://evil.example/steal")

        self.assertNotIn("evil.example", mail.outbox[-1].body)

    def test_an_account_has_no_password(self):
        self.ask_for_a_link("mira@example.com")

        self.assertFalse(User.objects.get().has_usable_password())


class FollowingTheLink(SignInTest):
    def test_opening_the_link_shows_a_button_and_does_not_sign_you_in(self):
        """Mail scanners open links. Only pressing the button signs anyone in."""
        self.ask_for_a_link("mira@example.com")

        response = self.client.get(self.link_from_the_email())

        self.assertContains(response, "<button")
        self.assert_signed_out()

    def test_pressing_the_button_signs_you_in(self):
        response = self.sign_in("mira@example.com")

        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/", follow=True), "mira@example.com")

    def test_you_land_on_the_page_you_first_asked_for(self):
        self.ask_for_a_link("mira@example.com", next="/worlds/the-moon/")

        response = self.client.post(self.link_from_the_email())

        self.assertRedirects(response, "/worlds/the-moon/", fetch_redirect_response=False)

    def test_you_are_never_sent_to_another_site(self):
        self.ask_for_a_link("mira@example.com", next="https://evil.example/steal")

        response = self.client.post(self.link_from_the_email())

        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_a_link_works_once(self):
        self.sign_in("mira@example.com")
        link = self.link_from_the_email()
        self.client.post("/sign-out/")

        response = self.client.post(link)

        self.assertContains(response, "This sign-in link has expired or already been used",
                            status_code=400)
        self.assert_signed_out()

    def test_a_made_up_link_does_not_work(self):
        response = self.client.post("/sign-in/link/?sesame=not-a-real-token")

        self.assertEqual(response.status_code, 400)
        self.assert_signed_out()

    @override_settings(SESAME_MAX_AGE=0)
    def test_an_old_link_does_not_work(self):
        self.ask_for_a_link("mira@example.com")

        response = self.client.post(self.link_from_the_email())

        self.assertEqual(response.status_code, 400)
        self.assert_signed_out()

    def test_a_link_signs_in_only_the_person_it_was_sent_to(self):
        self.ask_for_a_link("mira@example.com")
        self.ask_for_a_link("sam@example.com")

        self.client.post(self.link_from_the_email())

        home = self.client.get("/", follow=True)
        self.assertContains(home, "sam@example.com")
        self.assertNotContains(home, "mira@example.com")


class SigningOut(SignInTest):
    def test_signing_out_ends_the_session(self):
        self.sign_in()

        response = self.client.post("/sign-out/")

        self.assertRedirects(response, SIGN_IN)
        self.assert_signed_out()

    def test_a_link_cannot_sign_you_out(self):
        """Signing out is a form post, so a stray link or image cannot do it."""
        self.sign_in()

        response = self.client.get("/sign-out/")

        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.get("/", follow=True).status_code, 200)


class SignedIn(SignInTest):
    def test_the_sign_in_page_sends_you_home(self):
        self.sign_in()

        self.assertRedirects(self.client.get(SIGN_IN), "/", fetch_redirect_response=False)


@override_settings(EMAIL_BACKEND="accounts.email.TerminalEmailBackend")
class OnADevelopersMachine(SignInTest):
    def test_the_link_is_printed_in_the_terminal_ready_to_copy(self):
        import contextlib
        import io

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            self.ask_for_a_link("mira@example.com", next="/worlds/the-moon/")

        text = printed.getvalue()
        self.assertIn("To: mira@example.com", text)
        [link] = re.findall(r"http://testserver(/sign-in/link/\S+)", text)
        self.assertRedirects(self.client.post(link), "/worlds/the-moon/",
                             fetch_redirect_response=False)
