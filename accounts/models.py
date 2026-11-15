from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class UserManager(BaseUserManager):
    def tidy(self, email):
        """An email address in the one form it is stored and looked up in."""
        return email.strip().lower()

    def for_email(self, email):
        """The person with this email address, creating their account if this
        is the first time we have seen it. Accounts have no password."""
        user, created = self.get_or_create(email=self.tidy(email))
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user

    def remove_unused(self):
        """Delete the accounts that asked for a link long ago and never used
        one. Asking makes an account, so without this every address anyone
        ever typed would keep one. Someone who has never signed in has joined
        nothing, so nothing else refers to them. Returns how many went."""
        cutoff = timezone.now() - settings.SIGN_IN_UNUSED_ACCOUNT_AGE
        # An account someone has deactivated is kept, or asking again would
        # make it anew, and active.
        deleted, _ = self.filter(last_login__isnull=True, is_active=True,
                                 joined_at__lt=cutoff).delete()
        return deleted


class User(AbstractBaseUser):
    """A person who can sign in. They are known by their email address alone."""

    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"

    class Meta:
        constraints = [
            # One person per address, however it is capitalised. `for_email`
            # already stores addresses in lower case; this is the backstop.
            models.UniqueConstraint(Lower("email"), name="one_user_per_email"),
        ]

    def __str__(self):
        return self.email


class LimitCount(models.Model):
    """How many times something has happened lately, for a limit on it (see
    `plothelper.limits`). `key` is a hash of what is counted, such as the
    network address asking for sign-in links. A hash keeps the value out of
    plain sight, though one that can be guessed, such as an email address,
    can be found from it by trying. The count starts over once `expires_at`
    has passed."""

    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)
