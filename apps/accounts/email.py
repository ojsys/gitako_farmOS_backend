"""Email OTP delivery.

Goes through the shared branded mailer (HTML + text). In dev the backend is
`console` (prints to logs); production switches to SMTP via env (see settings).
"""
from __future__ import annotations

import logging

from gitako.mailer import send_branded_email

log = logging.getLogger("gitako.email")


def send_email_otp(*, email: str, code: str) -> None:
    """Email verification code (sign-up + sign-in use the same one-time code)."""
    send_branded_email(
        to=email,
        subject="Your Gitako verification code",
        heading="Verify your email",
        paragraphs=[
            "Enter the code below in the Gitako app to verify your email and "
            "finish signing in.",
        ],
        code=code,
        code_note="This code expires in 5 minutes.",
        footer_note="Didn’t request this? You can safely ignore this email — "
        "no changes will be made to your account.",
        preheader=f"Your Gitako verification code is {code}",
    )
    log.info("Email OTP %s sent to %s", code, email)


def send_welcome_email(*, email: str, name: str = "") -> None:
    """One-time welcome sent when a new account is created. Best-effort — it must
    never block sign-up, so failures are swallowed."""
    greeting = f"Welcome to Gitako, {name}!" if name else "Welcome to Gitako!"
    send_branded_email(
        to=email,
        subject="Welcome to Gitako 🌿",
        heading=greeting,
        paragraphs=[
            "Your account is ready — thanks for joining!",
            "Gitako helps you run your whole farm from one place: record what "
            "happens by voice, get an automatic GAP work calendar, track money "
            "and profit, and see how each season really performed.",
            "Open the app to set up your first farm, or manage everything from "
            "the web dashboard.",
        ],
        cta_label="Open the web dashboard",
        cta_url="https://app.gitako.com",
        footer_note="Need a hand getting started? Just reply to this email.",
        preheader="Your Gitako account is ready — here's how to get started.",
        fail_silently=True,
    )
    log.info("Welcome email sent to %s", email)
