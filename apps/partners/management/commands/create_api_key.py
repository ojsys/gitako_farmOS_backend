"""Mint an API key for a partner. The raw key is printed ONCE — store it now.

Usage:
  manage.py create_api_key --partner "Sterling MFI" --create-partner --label "prod"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.partners.auth import generate_api_key
from apps.partners.models import ApiKey, Partner


class Command(BaseCommand):
    help = "Create an API key for a partner (prints the raw key once)."

    def add_arguments(self, parser):
        parser.add_argument("--partner", required=True, help="Partner name.")
        parser.add_argument("--create-partner", action="store_true",
                            help="Create the partner if it doesn't exist.")
        parser.add_argument("--kind", default="other")
        parser.add_argument("--label", default="")

    def handle(self, *args, **opts):
        name = opts["partner"]
        partner = Partner.objects.filter(name=name).first()
        if partner is None:
            if not opts["create_partner"]:
                raise CommandError(f"Partner '{name}' not found. Use --create-partner to create it.")
            partner = Partner.objects.create(name=name, kind=opts["kind"])
            self.stdout.write(self.style.SUCCESS(f"Created partner {partner.id} ({name})"))

        raw, prefix, key_hash = generate_api_key()
        ApiKey.objects.create(partner=partner, prefix=prefix, key_hash=key_hash, label=opts["label"])
        self.stdout.write(self.style.WARNING("API key (shown once — store it securely):"))
        self.stdout.write(raw)
