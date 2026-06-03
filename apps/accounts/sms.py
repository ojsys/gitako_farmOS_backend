"""SMS provider abstraction.

Dev default: console provider (logs the code). Production: Termii. Wire the
provider via the GITAKO['SMS_PROVIDER'] setting.
"""
from __future__ import annotations

import logging
from typing import Protocol

import requests
from django.conf import settings

log = logging.getLogger("gitako.sms")


class SmsProvider(Protocol):
    def send(self, *, phone: str, message: str) -> None: ...

    def send_otp(self, *, phone: str, code: str) -> None: ...


class ConsoleSmsProvider:
    def send(self, *, phone: str, message: str) -> None:
        log.info("SMS to %s (dev console provider): %s", phone, message)

    def send_otp(self, *, phone: str, code: str) -> None:
        self.send(phone=phone, message=f"Your Gitako code is {code}. It expires in 5 minutes.")


class TermiiSmsProvider:
    BASE_URL = "https://api.ng.termii.com"

    def send(self, *, phone: str, message: str) -> None:
        cfg = settings.GITAKO
        if not cfg["TERMII_API_KEY"]:
            log.warning("Termii API key not configured; falling back to console")
            ConsoleSmsProvider().send(phone=phone, message=message)
            return
        resp = requests.post(
            f"{self.BASE_URL}/api/sms/send",
            json={
                "to": phone,
                "from": cfg["TERMII_SENDER_ID"],
                "sms": message,
                "type": "plain",
                "channel": "generic",
                "api_key": cfg["TERMII_API_KEY"],
            },
            timeout=10,
        )
        resp.raise_for_status()

    def send_otp(self, *, phone: str, code: str) -> None:
        self.send(phone=phone, message=f"Your Gitako code is {code}. It expires in 5 minutes.")


def get_provider() -> SmsProvider:
    name = settings.GITAKO["SMS_PROVIDER"]
    if name == "termii":
        return TermiiSmsProvider()
    return ConsoleSmsProvider()
