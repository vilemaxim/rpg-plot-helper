from django.contrib.auth.views import redirect_to_login
from django.urls import Resolver404, resolve


def is_public(path):
    """Whether a signed-out person may see this path. Only views marked with
    Django's `login_not_required` are public; a path that leads nowhere is not,
    so a signed-out person cannot learn which pages exist."""
    try:
        view = resolve(path).func
    except Resolver404:
        return False
    return getattr(view, "login_required", True) is False


class SignInRequiredMiddleware:
    """Send a signed-out person to sign-in, whatever page they asked for."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not is_public(request.path_info):
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)
