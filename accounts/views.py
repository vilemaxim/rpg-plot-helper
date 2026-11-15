from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_not_required
from django.core.mail import send_mail
from django.shortcuts import redirect, render, resolve_url
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode
from django.views.decorators.http import require_http_methods, require_POST
from sesame import settings as link_settings
from sesame.utils import get_token

from plothelper import limits

from .forms import SignInForm
from .models import User

TOKEN = link_settings.TOKEN_NAME


def safe_next(request, url):
    """Where to send someone after sign-in: the page they asked for if it is
    on this site, and the home page otherwise."""
    if url and url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return resolve_url(settings.LOGIN_REDIRECT_URL)


def send_sign_in_link(request, user, next_url):
    query = {TOKEN: get_token(user)}
    if next_url and next_url == safe_next(request, next_url):
        query["next"] = next_url
    link = request.build_absolute_uri(f"{reverse('sign-in-link')}?{urlencode(query)}")
    minutes = int(link_settings.MAX_AGE // 60)
    # Sent while the request runs, not after it: on hosting that stops an
    # instance once its response is sent, mail sent afterwards can be lost.
    send_mail(
        subject="Your sign-in link for RPG Plot Helper",
        message=render_to_string("accounts/sign_in_email.txt",
                                 {"link": link, "minutes": minutes}),
        from_email=None,
        recipient_list=[user.email],
    )


def within_limits(request, email):
    """Count this request against the limits on sign-in links, and say
    whether a link may be sent. The requester is counted first, and the
    email address only if the requester is within its limit: otherwise
    someone over their own limit could keep counting a stranger's address
    and stop them ever getting a link."""
    if not limits.take("sign-in-requester", limits.requester(request),
                       settings.SIGN_IN_LINKS_PER_REQUESTER, settings.SIGN_IN_REQUESTER_WINDOW):
        return False
    return limits.take("sign-in-address", email, settings.SIGN_IN_LINKS_PER_ADDRESS,
                       settings.SIGN_IN_ADDRESS_WINDOW)


@login_not_required
@require_http_methods(["GET", "POST"])
def sign_in(request):
    """Ask for an email address and send it a sign-in link."""
    if request.user.is_authenticated:
        # A link that names an address, such as an invitation, is for that
        # address only. Say so rather than quietly sending them home.
        wanted = User.objects.tidy(request.GET.get("email", ""))
        if wanted and wanted != request.user.email:
            return render(request, "accounts/other_address.html", {"wanted": wanted})
        return redirect(safe_next(request, request.GET.get("next")))

    if request.method == "GET":
        # An invitation links here with the invited address filled in.
        form = SignInForm(initial={"next": request.GET.get("next", ""),
                                   "email": request.GET.get("email", "")})
        return render(request, "accounts/sign_in.html", {"form": form})

    form = SignInForm(request.POST)
    if not form.is_valid():
        return render(request, "accounts/sign_in.html", {"form": form})

    User.objects.remove_unused()
    email = User.objects.tidy(form.cleaned_data["email"])
    response = render(request, "accounts/link_sent.html", {"email": email})
    if not within_limits(request, email):
        # The same page, and no email, so being limited tells no one anything.
        return response
    user = User.objects.for_email(email)
    if user.is_active:
        send_sign_in_link(request, user, form.cleaned_data["next"])
    return response


@login_not_required
@require_http_methods(["GET", "POST"])
def follow_link(request):
    """The page a sign-in link opens. Opening it only shows a button, because
    mail scanners open links and would use the link up; pressing the button is
    what signs the person in."""
    if request.method == "GET":
        return render(request, "accounts/follow_link.html")

    user = authenticate(request, sesame=request.GET.get(TOKEN, ""))
    if user is not None:
        # A link works once: signing in changes `last_login`, which ends it.
        # Two requests with one link at the same moment could both check it
        # before either signs in, so the second waits here for the first and
        # finds the link already used.
        locked = User.objects.select_for_update().filter(pk=user.pk).first()
        if locked is None or locked.last_login != user.last_login:
            user = None
    if user is None:
        return render(request, "accounts/link_expired.html", status=400)
    login(request, user)
    return redirect(safe_next(request, request.GET.get("next")))


@login_not_required
@require_POST
def sign_out(request):
    logout(request)
    return redirect("sign-in")
