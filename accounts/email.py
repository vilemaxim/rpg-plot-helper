import sys

from django.core.mail.backends.base import BaseEmailBackend


class TerminalEmailBackend(BaseEmailBackend):
    """Print each email in the terminal instead of sending it.

    Django's own console backend prints the encoded message, which breaks a
    long link across lines and turns `=` into `=3D`. This one prints the text
    as written, so a sign-in link can be copied straight out of the terminal.
    """

    def send_messages(self, email_messages):
        for message in email_messages:
            sys.stdout.write(
                f"\n{'─' * 72}\n"
                f"To: {', '.join(message.to)}\n"
                f"Subject: {message.subject}\n\n"
                f"{message.body}\n"
                f"{'─' * 72}\n"
            )
        sys.stdout.flush()
        return len(email_messages)
