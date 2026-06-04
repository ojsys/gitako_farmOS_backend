"""Branded transactional email — one helper all outgoing mail goes through.

Renders the `email/base.html` template (a responsive, inline-styled shell) and
sends a multipart message (HTML + plain-text fallback) so every email looks the
same and degrades gracefully in text-only clients.

Usage:
    from gitako.mailer import send_branded_email
    send_branded_email(
        to="user@example.com",
        subject="Your Gitako code",
        heading="Your verification code",
        paragraphs=["Use the code below to finish signing in."],
        code="482913",
        code_note="Expires in 5 minutes",
    )
"""
from __future__ import annotations

from datetime import datetime
from collections.abc import Iterable

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

SITE_URL = "https://www.gitako.com"


def send_branded_email(
    *,
    to: str | Iterable[str],
    subject: str,
    heading: str,
    paragraphs: list[str] | None = None,
    code: str | None = None,
    code_note: str | None = None,
    cta_label: str | None = None,
    cta_url: str | None = None,
    footer_note: str | None = None,
    preheader: str | None = None,
    fail_silently: bool = False,
) -> None:
    paragraphs = paragraphs or []
    recipients = [to] if isinstance(to, str) else list(to)

    context = {
        "subject": subject,
        "preheader": preheader or (paragraphs[0] if paragraphs else heading),
        "heading": heading,
        "paragraphs": paragraphs,
        "code": code,
        "code_note": code_note,
        "cta_label": cta_label,
        "cta_url": cta_url,
        "footer_note": footer_note,
        "year": datetime.now().year,
        "site_url": SITE_URL,
        "site_url_label": SITE_URL.replace("https://", ""),
    }
    html_body = render_to_string("email/base.html", context)
    text_body = _plain_text(
        heading, paragraphs, code, code_note, cta_label, cta_url, footer_note
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        to=recipients,
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send(fail_silently=fail_silently)


def _plain_text(heading, paragraphs, code, code_note, cta_label, cta_url, footer_note) -> str:
    lines: list[str] = [heading, ""]
    lines += list(paragraphs)
    if code:
        lines += ["", f"Code: {code}"]
        if code_note:
            lines.append(code_note)
    if cta_url:
        lines += ["", f"{cta_label or 'Open'}: {cta_url}"]
    if footer_note:
        lines += ["", footer_note]
    lines += ["", f"— Gitako · {SITE_URL}"]
    return "\n".join(lines).strip() + "\n"
