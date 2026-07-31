from django.db import IntegrityError, transaction
from django.db.models.functions import Length

from busstops.models import Operator
from busstops.bustimes_sync import apply_sync_fields, compact_registration, compact_text
from vehicles.models import Vehicle, VehicleCode, VehicleFeature

from ._sync_bustimes import (
    BUSTIMES_SCHEME,
    BUSTIMES_SLUG_SCHEME,
    BUSTIMES_SOURCE_NAME,
    BustimesSyncCommand,
    api_id,
    locally_edited_vehicle_fields,
    resolve_garage,
    resolve_livery,
    resolve_operator,
    resolve_or_create_garage,
    resolve_or_create_livery,
    resolve_vehicle,
    resolve_vehicle_type,
)


class Command(BustimesSyncCommand):
    help = "Sync vehicles from the Bustimes API."
    endpoint = "vehicles/"

    VEHICLE_SHORT_FIELD_MAX_LENGTH = 24
    SUPPORTED_SYNC_FIELDS = {
        "source",
        "code",
        "fleet_code",
        "fleet_number",
        "reg",
        "prev_registration",
        "data",
        "operator",
        "vehicle_type",
        "livery",
        "garage",
        "name",
        "branding",
        "notes",
        "withdrawn",
        "preserved",
        "fleet_support_vehicle",
        "vor",
        "awaiting_delivery",
        "trainer_vehicle",
        "demonstrator",
        "features",
    }

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--operator",
            help="Operator NOC/code filter to pass to the Bustimes vehicles endpoint.",
        )
        parser.add_argument(
            "--slug",
            help="Vehicle slug filter to sync a specific vehicle.",
        )
        parser.add_argument(
            "--fields",
            nargs="+",
            choices=sorted(self.SUPPORTED_SYNC_FIELDS),
            help="Only sync these vehicle fields.",
        )
        parser.add_argument(
            "--override",
            action="store_true",
            help="Override existing data with Bustimes API data, creating new garages if needed.",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Show debug output for livery resolution.",
        )
        parser.add_argument(
            "--new-table",
            action="store_true",
            help="Use bustimes slug for vehicle slug instead of auto-generated slug.",
        )

    def get_query_params(self, options):
        params = {"withdrawn": "false"}
        operator = compact_text(options.get("operator"))
        if operator:
            params["operator"] = operator
        slug = compact_text(options.get("slug"))
        if slug:
            params["slug"] = slug
        return params

    def fit_short_text(self, value):
        return compact_text(value)[: self.VEHICLE_SHORT_FIELD_MAX_LENGTH]

    def fit_registration(self, value):
        return compact_registration(value)[: self.VEHICLE_SHORT_FIELD_MAX_LENGTH]

    def payload_vehicle(self, item):
        vehicle_data = item.get("vehicle")
        return vehicle_data if isinstance(vehicle_data, dict) else {}

    def get_payload_value(self, item, *keys):
        vehicle_data = self.payload_vehicle(item)
        for key in keys:
            value = item.get(key)
            if value not in (None, ""):
                return value
        for key in keys:
            value = vehicle_data.get(key)
            if value not in (None, ""):
                return value
        return None

    def get_payload_bool(self, item, *keys):
        value = self.get_payload_value(item, *keys)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            value = value.strip().lower()
            if value in {"1", "true", "yes", "y", "on"}:
                return True
            if value in {"0", "false", "no", "n", "off"}:
                return False
        return None

    def selected_fields(self, options):
        fields = options.get("fields")
        return set(fields) if fields else None

    def filter_values(self, values, options):
        fields = self.selected_fields(options)
        if fields is None:
            return values
        return {key: value for key, value in values.items() if key in fields}

    def get_special_feature_names(self, item):
        vehicle_data = self.payload_vehicle(item)
        if "special_features" in item:
            value = item.get("special_features")
        elif "features" in item:
            value = item.get("features")
        elif "special_features" in vehicle_data:
            value = vehicle_data.get("special_features")
        elif "features" in vehicle_data:
            value = vehicle_data.get("features")
        else:
            return None
        if value is None:
            return None
        if not value:
            return []
        if not isinstance(value, list):
            value = [value]
        names = []
        seen = set()
        for feature in value:
            if isinstance(feature, dict):
                feature = (
                    feature.get("name")
                    or feature.get("text")
                    or feature.get("label")
                    or feature.get("title")
                )
            name = compact_text(feature)
            if not name:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            names.append(name)
        return names

    def get_batched_operator_nocs(self):
        return list(
            Operator.objects.filter(
                source=self.get_source(),
                is_manual=False,
            )
            .annotate(noc_length=Length("noc"))
            .filter(noc_length=4)
            .exclude(external_id__startswith="stagecoach-garage:")
            .order_by("noc")
            .values_list("noc", flat=True)
        )

    def values_from_item(self, item, vehicle, options=None):
        if options is None:
            options = {}
        operator = resolve_operator(self.get_payload_value(item, "operator"))
        fleet_code = self.fit_short_text(
            self.get_payload_value(item, "fleet_code", "fleet_number", "code")
        )
        reg = self.fit_registration(self.get_payload_value(item, "reg", "registration"))
        
        # Use {REG}_{FLEET_NUMBER} format for code
        if reg and fleet_code:
            code = f"{reg}_{fleet_code}"
        elif reg:
            code = reg
        elif fleet_code:
            code = fleet_code
        else:
            # Fallback to api_id, but ensure it's never empty
            code = api_id(item)
            if not code:
                import uuid
                code = f"temp-{uuid.uuid4().hex[:8]}"
        
        # Ensure code is never empty
        if not code:
            import uuid
            code = f"temp-{uuid.uuid4().hex[:8]}"

        # Use resolve_or_create_garage if override is set
        garage_value = self.get_payload_value(item, "garage")
        if options.get("override"):
            garage = resolve_or_create_garage(garage_value, operator=operator)
        else:
            garage = resolve_garage(garage_value, operator=operator)

        # Use resolve_or_create_livery if override is set
        livery_value = self.get_payload_value(item, "livery")
        if options.get("override"):
            livery = resolve_or_create_livery(livery_value, debug=options.get("debug", False), skip_sync_state=True)
        else:
            livery = resolve_livery(livery_value)

        values = {
            "source": self.get_source(),
            "code": code,
            "fleet_code": fleet_code,
            "reg": reg,
            "operator": operator,
            "vehicle_type": resolve_vehicle_type(
                self.get_payload_value(item, "vehicle_type", "type")
            ),
            "livery": livery,
            "garage": garage,
            "name": compact_text(self.get_payload_value(item, "name")),
            "branding": compact_text(self.get_payload_value(item, "branding")),
            "notes": compact_text(self.get_payload_value(item, "notes")),
        }

        # Use bustimes slug when --new-table flag is set
        if options.get("new_table"):
            bustimes_slug = compact_text(item.get("slug"))
            if bustimes_slug:
                values["slug"] = bustimes_slug

        if fleet_code.isdigit():
            values["fleet_number"] = int(fleet_code)

        previous_reg = self.fit_registration(
            self.get_payload_value(item, "prev_registration", "previous_reg", "previous_reg")
        )
        if previous_reg:
            if hasattr(vehicle, "prev_registration"):
                values["prev_registration"] = previous_reg
            else:
                data = dict(getattr(vehicle, "data", None) or {})
                data["Previous reg"] = previous_reg
                values["data"] = data

        for field_name in (
            "withdrawn",
            "preserved",
            "fleet_support_vehicle",
            "vor",
            "awaiting_delivery",
            "trainer_vehicle",
            "demonstrator",
        ):
            value = self.get_payload_bool(item, field_name)
            if value is not None:
                values[field_name] = value

        return {key: value for key, value in values.items() if value not in (None, "")}

    def resolve_special_features(self, item):
        feature_names = self.get_special_feature_names(item)
        if feature_names is None:
            return None
        features = []
        for name in feature_names:
            feature = VehicleFeature.objects.filter(name__iexact=name).first()
            if not feature:
                feature = VehicleFeature.objects.create(name=name)
            features.append(feature)
        return features

    def get_merge_target(self, vehicle, values):
        operator = values.get("operator")
        code = compact_text(values.get("code"))
        if not operator:
            return vehicle
        if code:
            candidates = Vehicle.objects.filter(operator=operator, code__iexact=code)
        else:
            candidates = Vehicle.objects.filter(operator=operator, code="")
        if vehicle.pk:
            candidates = candidates.exclude(pk=vehicle.pk)
        return candidates.first() or vehicle

    def get_conflicting_vehicle(self, vehicle, values):
        operator = values.get("operator") or getattr(vehicle, "operator", None)
        code = compact_text(values.get("code", getattr(vehicle, "code", "")))
        if not operator:
            return None
        if code:
            candidates = Vehicle.objects.filter(operator=operator, code__iexact=code)
        else:
            candidates = Vehicle.objects.filter(operator=operator, code="")
        if vehicle.pk:
            candidates = candidates.exclude(pk=vehicle.pk)
        return candidates.first()

    def merge_vehicle_records(self, source_vehicle, target_vehicle):
        if (
            not source_vehicle.pk
            or not target_vehicle.pk
            or source_vehicle.pk == target_vehicle.pk
        ):
            return target_vehicle

        # Ensure target_vehicle is saved before updating related records
        if not target_vehicle.pk:
            target_vehicle.save()

        source_vehicle.vehiclejourney_set.update(vehicle=target_vehicle)
        source_vehicle.vehiclerevision_set.update(vehicle=target_vehicle)

        for code in source_vehicle.vehiclecode_set.all():
            existing = VehicleCode.objects.filter(
                scheme=code.scheme,
                code=code.code,
            ).exclude(pk=code.pk).first()
            if existing:
                if existing.vehicle_id == target_vehicle.pk:
                    code.delete()
                continue
            code.vehicle = target_vehicle
            code.save(update_fields=["vehicle"])

        if source_vehicle.latest_journey_id and (
            not target_vehicle.latest_journey_id
            or source_vehicle.latest_journey.datetime > target_vehicle.latest_journey.datetime
        ):
            # Check if latest_journey_id is already used by another vehicle
            if not Vehicle.objects.filter(
                latest_journey_id=source_vehicle.latest_journey_id
            ).exclude(pk=target_vehicle.pk).exists():
                target_vehicle.latest_journey = source_vehicle.latest_journey
                target_vehicle.save(update_fields=["latest_journey"])

        if source_vehicle.latest_journey_id:
            source_vehicle.latest_journey = None
            source_vehicle.save(update_fields=["latest_journey"])
        source_vehicle.delete()
        return target_vehicle

    @transaction.atomic
    def sync_item(self, item, options):
        vehicle = resolve_vehicle(item) or Vehicle()
        values = self.filter_values(self.values_from_item(item, vehicle, options), options)
        merge_target = self.get_merge_target(vehicle, values)
        if options["dry_run"]:
            vehicle = merge_target
        else:
            vehicle = self.merge_vehicle_records(vehicle, merge_target)

        # When using --override, bypass locked check
        if getattr(vehicle, "locked", False) and vehicle.pk and not options["force"] and not options.get("override"):
            return False, False, 1

        # Skip locally edited fields check when using --override
        if not options.get("override"):
            for field in locally_edited_vehicle_fields(vehicle):
                values.pop(field, None)
            protected_fields = locally_edited_vehicle_fields(vehicle)
        else:
            protected_fields = set()

        # When using --override, clear protected fields from sync state
        if options.get("override") and not options["dry_run"]:
            from busstops.models import BustimesSyncState
            external_id = api_id(item)
            if external_id:
                BustimesSyncState.objects.filter(
                    object_type="vehicle",
                    external_id=str(external_id),
                ).update(protected_fields=[])

        try:
            result = apply_sync_fields(
                instance=vehicle,
                object_type="vehicle",
                external_id=api_id(item),
                values=values,
                payload=item,
                dry_run=options["dry_run"],
                force=options["force"] or options.get("override"),
            )
        except IntegrityError as exc:
            is_vehicle_code_conflict = "vehicle_operator_and_code" in str(exc)
            conflicting_vehicle = self.get_conflicting_vehicle(vehicle, values)
            if (
                options["dry_run"]
                or not is_vehicle_code_conflict
                or not vehicle.pk
                or not conflicting_vehicle
            ):
                raise
            vehicle = self.merge_vehicle_records(vehicle, conflicting_vehicle)
            result = apply_sync_fields(
                instance=vehicle,
                object_type="vehicle",
                external_id=api_id(item),
                values=values,
                payload=item,
                dry_run=options["dry_run"],
                force=options["force"] or options.get("override"),
            )

        if not options["dry_run"] and vehicle.pk:
            codes = (
                (BUSTIMES_SCHEME, api_id(item)),
                (BUSTIMES_SLUG_SCHEME, compact_text(item.get("slug"))),
            )
            for scheme, code_value in codes:
                if not code_value:
                    continue
                try:
                    code, _ = VehicleCode.objects.get_or_create(
                        scheme=scheme,
                        code=code_value,
                        defaults={"vehicle": vehicle},
                    )
                    if code.vehicle_id != vehicle.pk:
                        code.vehicle = vehicle
                        code.save(update_fields=["vehicle"])
                except IntegrityError:
                    pass
            selected_fields = self.selected_fields(options)
            should_sync_features = selected_fields is None or "features" in selected_fields
            if should_sync_features and "features" not in protected_fields:
                features = self.resolve_special_features(item)
                if features is not None:
                    vehicle.features.set(features)
        return result.created, result.updated, len(result.skipped_fields)

    def sync_items(self, options):
        created = updated = skipped = 0
        processed = 0
        progress = self.progress(options)
        for item in self.iter_items_with_progress(options, progress):
            item_created, item_updated, item_skipped = self.sync_item(item, options)
            created += int(item_created)
            updated += int(item_updated)
            skipped += item_skipped
            processed += 1
            progress.tick(created=item_created, updated=item_updated, skipped=item_skipped)
        return created, updated, skipped, processed

    def handle(self, *args, **options):
        # If --new-table flag is set, delete all vehicles and liveries first
        if options.get("new_table"):
            self.stdout.write("Clearing latest_journey references...")
            Vehicle.objects.all().update(latest_journey=None)
            self.stdout.write("Deleting vehicle features...")
            from vehicles.models import VehicleFeature
            VehicleFeature.objects.all().delete()
            self.stdout.write("Deleting all vehicles...")
            Vehicle.objects.all().delete()
            self.stdout.write("Deleting all liveries...")
            from vehicles.models import Livery
            Livery.objects.all().delete()
            self.stdout.write("All vehicles, liveries, and features deleted.")
        
        explicit_operator = compact_text(options.get("operator"))
        if explicit_operator:
            created, updated, skipped, _processed = self.sync_items(options)
            self.print_summary(created, updated, skipped)
            return

        operator_nocs = self.get_batched_operator_nocs()
        if not operator_nocs:
            created, updated, skipped, _processed = self.sync_items(options)
            self.print_summary(created, updated, skipped)
            return

        self.stdout.write(
            f"Batching vehicle sync by {len(operator_nocs)} Bustimes operators from {BUSTIMES_SOURCE_NAME}."
        )

        created = updated = skipped = 0
        remaining = options.get("max_items")
        for noc in operator_nocs:
            if remaining is not None and remaining <= 0:
                break
            batch_options = dict(options)
            batch_options["operator"] = noc
            if remaining is not None:
                batch_options["max_items"] = remaining
            item_created, item_updated, item_skipped, processed = self.sync_items(
                batch_options
            )
            created += item_created
            updated += item_updated
            skipped += item_skipped
            if remaining is not None:
                remaining -= processed
        self.print_summary(created, updated, skipped)
