"""Email OTP delivery.

Uses Django's email backend, which in dev is `django.core.mail.backends.console`
(prints messages to docker logs). Production switches via DJANGO_EMAIL_BACKEND
+ SMTP creds in settings.
"""
from __future__ import annotations

import logging

from django.core.mail import send_mail

log = logging.getLogger("gitako.email")


def send_email_otp(*, email: str, code: str) -> None:
    subject = "Your Gitako code"
    body = (
        f"Your Gitako code is {code}.\n"
        f"It expires in 5 minutes.\n\n"
        f"If you didn't request this, you can ignore this email."
    )
    send_mail(
        subject=subject,
        message=body,
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        recipient_list=[email],
        fail_silently=False,
    )
    log.info("Email OTP %s sent to %s", code, email)
