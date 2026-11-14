from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


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
