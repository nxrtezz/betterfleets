import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import requests

from vehicles.realtime import bods_auth
from vehicles.views import _get_bods_datafeed_url, _get_bods_operator_refs, _get_bods_vehicles


class Command(BaseCommand):
    help = "Fetch live BODS vehicles for one or more operators"

    def add_arguments(self, parser):
        parser.add_argument(
            "--noc",
            dest="nocs",
            action="append",
            help="Operator NOC (repeatable) or comma-separated list",
        )
        parser.add_argument(
            "--operator-ref",
            dest="operator_refs",
            action="append",
            help="Raw BODS OperatorRef (repeatable) or comma-separated list",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Max vehicles to print in summary mode",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Print full JSON output",
        )
        parser.add_argument(
            "--api-key",
            dest="api_key",
            help="Override BODS API key for this command run",
        )
        parser.add_argument(
            "--show-http",
            action="store_true",
            help="Show HTTP status and first part of response body",
        )
        parser.add_argument(
            "--auth-mode",
            choices=("query", "header", "both"),
            default=None,
            help="How to send API key for debug probe request",
        )

    @staticmethod
    def _split_values(values):
        result = []
        for value in values or []:
            result.extend(item.strip() for item in value.split(",") if item.strip())
        return result

    def handle(self, *args, **options):
        nocs = self._split_values(options["nocs"])
        operator_refs = self._split_values(options["operator_refs"])

        operator_ids = [*nocs, *operator_refs]
        if not operator_ids:
            raise CommandError(
                "Provide at least one --noc or --operator-ref (repeatable or comma-separated)."
            )

        if options.get("api_key"):
            settings.BODS_API_KEY = options["api_key"]

        api_key = settings.BODS_API_KEY or ""
        self.stdout.write(f"api_key_configured={'yes' if api_key else 'no'}")

        auth_mode = options.get("auth_mode")
        if auth_mode:
            self.stdout.write(f"auth_mode_override={auth_mode}")
        if options.get("show_http"):
            self._debug_http_probe(api_key, auth_mode)

        resolved_refs = sorted(_get_bods_operator_refs(operator_ids))
        vehicles = _get_bods_vehicles(operator_ids)

        self.stdout.write(f"input_operator_ids={','.join(operator_ids)}")
        self.stdout.write(f"resolved_operator_refs={','.join(resolved_refs)}")
        self.stdout.write(f"vehicle_count={len(vehicles)}")

        if options["json"]:
            self.stdout.write(json.dumps(vehicles, indent=2))
            return

        limit = max(options["limit"], 0)
        for vehicle in vehicles[:limit]:
            vehicle_name = (vehicle.get("vehicle") or {}).get("name", "")
            service = (vehicle.get("service") or {}).get("line_name", "")
            destination = vehicle.get("destination", "")
            coordinates = vehicle.get("coordinates")
            self.stdout.write(
                f"id={vehicle['id']} vehicle={vehicle_name} line={service} "
                f"dest={destination} coords={coordinates}"
            )

    def _debug_http_probe(self, api_key: str, auth_mode: str | None):
        url = _get_bods_datafeed_url()
        request_kwargs = bods_auth.get_bods_request_kwargs(api_key, auth_mode)
        request_kwargs["timeout"] = 20
        effective_auth_mode = (auth_mode or "from-settings").lower()

        try:
            response = requests.get(url, **request_kwargs)
        except requests.RequestException as exc:
            self.stdout.write(f"http_probe_error={exc}")
            return

        self.stdout.write(
            f"http_probe mode={effective_auth_mode} status={response.status_code} "
            f"content_type={response.headers.get('content-type','')}"
        )
        body = (response.text or "").strip()
        if body:
            self.stdout.write(f"http_probe_body={body[:500]}")
