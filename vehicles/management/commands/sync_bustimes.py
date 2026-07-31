from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from tqdm import tqdm

from busstops.bustimes_sync import BustimesApiClient, compact_text, compact_registration
from busstops.management.commands._sync_bustimes import resolve_operator, resolve_livery, resolve_garage, resolve_or_create_garage
from busstops.models import Operator, OperatorGroup, Organisation
from vehicles.models import Livery, Vehicle, VehicleCode


class Command(BaseCommand):
    VERSION = "V1"
    help = "Sync vehicles against the Bustimes API, checking fleet num, operator, livery, and name."

    def add_arguments(self, parser):
        parser.add_argument("--operator", help="Operator NOC to filter vehicles.")
        parser.add_argument(
            "--organisation",
            "--organization",
            dest="organisation",
            help="Organisation slug to filter vehicles.",
        )
        parser.add_argument(
            "--operator-group",
            "--operator_group",
            dest="operator_group",
            help="Operator group slug to filter vehicles.",
        )
        parser.add_argument("--livery", type=int, help="Livery ID to filter vehicles.")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the previewed changes without an interactive confirmation prompt.",
        )
        parser.add_argument(
            "--override",
            action="store_true",
            help="Override existing data with Bustimes API data, creating new garages if needed.",
        )
        parser.add_argument(
            "--fields",
            nargs="+",
            choices=["fleet_number", "livery", "vehicle_type"],
            help="Only sync specific fields from Bustimes API. If not specified, all fields will be checked.",
        )

    def handle(self, *args, **options):
        vehicles = self._resolve_scope(options)
        self.fields_to_check = options.get("fields")
        
        if not vehicles:
            self.stdout.write("No vehicles found matching the specified criteria.")
            return

        vehicles = list(vehicles.select_related("operator", "livery", "garage").order_by("id"))
        self.stdout.write(f"Found {len(vehicles)} vehicle(s) to check against Bustimes API.")
        if self.fields_to_check:
            self.stdout.write(f"Only checking fields: {', '.join(self.fields_to_check)}")

        client = BustimesApiClient()
        
        results = []
        failures = []
        skipped_stagecoach = 0

        progress = tqdm(
            vehicles,
            desc="Checking vehicles",
            unit="vehicle",
            file=self.stdout,
            disable=not vehicles,
        )

        for vehicle in progress:
            try:
                result = self._check_vehicle_per_api(vehicle, client)
                if result == "stagecoach":
                    skipped_stagecoach += 1
                elif result:
                    results.append(result)
            except Exception as exc:
                failures.append((vehicle, str(exc)))
                continue

        self._write_preview(results, failures, skipped_stagecoach)

        if not results:
            self.stdout.write("No differences found between local and Bustimes API data.")
            return

        if options["apply"]:
            self._apply_updates(results, override=options.get("override", False))
            return

        if self._confirm_apply():
            self._apply_updates(results, override=options.get("override", False))
        else:
            self.stdout.write("Cancelled. No changes were applied.")

    def _resolve_scope(self, options):
        provided = [
            bool(options.get("operator")),
            bool(options.get("organisation")),
            bool(options.get("operator_group")),
            bool(options.get("livery")),
        ]
        
        # If no filters provided, return all vehicles (excluding withdrawn)
        if not any(provided):
            return Vehicle.objects.filter(withdrawn=False)

        # Ensure only one scope filter is provided (except livery which can be combined)
        scope_provided = [
            bool(options.get("operator")),
            bool(options.get("organisation")),
            bool(options.get("operator_group")),
        ]
        if sum(scope_provided) > 1:
            raise CommandError(
                "Provide only one of --operator, --organisation, or --operator-group."
            )

        queryset = Vehicle.objects.filter(withdrawn=False)

        if options.get("operator"):
            operator = Operator.objects.filter(noc__iexact=options["operator"]).first()
            if not operator:
                raise CommandError(f"Operator {options['operator']} was not found.")
            queryset = queryset.filter(operator=operator)

        elif options.get("organisation"):
            organisation = Organisation.objects.filter(slug=options["organisation"]).first()
            if not organisation:
                raise CommandError(f"Organisation {options['organisation']} was not found.")
            queryset = queryset.filter(operator__organisation=organisation)

        elif options.get("operator_group"):
            operator_group = OperatorGroup.objects.filter(slug=options["operator_group"]).first()
            if not operator_group:
                raise CommandError(f"Operator group {options['operator_group']} was not found.")
            queryset = queryset.filter(operator__group=operator_group)

        if options.get("livery"):
            livery = Livery.objects.filter(pk=options["livery"]).first()
            if not livery:
                raise CommandError(f"Livery {options['livery']} was not found.")
            queryset = queryset.filter(livery=livery)

        return queryset

    def _should_check_field(self, field_name):
        """Check if a field should be checked based on the --fields argument."""
        if self.fields_to_check is None:
            return True  # Check all fields if no filter specified
        return field_name in self.fields_to_check

    def _check_vehicle_per_api(self, vehicle, client):
        """
        Query Bustimes API for a specific vehicle by registration.
        Match vehicles using reg, fleet code, livery css, garage, vehicle type, and features.
        Returns differences if found, 'stagecoach' if operator contains Stagecoach, None if no match or no differences.
        """
        from busstops.management.commands._sync_bustimes import normalise_bustimes_livery
        
        # Get the vehicle's registration
        if not vehicle.reg:
            return None
        
        reg = compact_registration(vehicle.reg)
        if not reg:
            return None
        
        # Query Bustimes API for vehicles with this registration that are NOT withdrawn
        api_params = {
            "reg": reg,
            "withdrawn": "false"
        }
        
        try:
            # Get vehicles from API - get multiple to find best match
            vehicles_list = list(client.iter_results("vehicles/", limit=10, params=api_params))
            
            if not vehicles_list:
                return None  # No vehicle found in API
            
        except Exception as exc:
            raise Exception(f"API query failed for reg {reg}: {str(exc)}")
        
        # Find the best matching vehicle based on multiple criteria
        best_match = None
        best_match_score = 0
        
        for data in vehicles_list:
            # Check if operator contains "Stagecoach" - skip if so
            api_operator_noc = None
            if data.get("operator"):
                if isinstance(data["operator"], dict):
                    api_operator_noc = data["operator"].get("noc") or data["operator"].get("id")
                    api_operator_name = data["operator"].get("name", "")
                else:
                    api_operator_noc = data["operator"]
                    api_operator_name = ""
            
            if api_operator_name and "stagecoach" in api_operator_name.lower():
                continue  # Skip Stagecoach vehicles
            
            score = 0
            
            # Match by fleet code
            api_fleet_code = compact_text(data.get("fleet_code") or data.get("fleet_number"))
            vehicle_fleet_code = compact_text(vehicle.fleet_code or vehicle.fleet_number)
            if api_fleet_code and vehicle_fleet_code and api_fleet_code == vehicle_fleet_code:
                score += 3
            
            # Match by livery CSS
            api_livery_data = data.get("livery")
            if api_livery_data and vehicle.livery:
                livery_data = normalise_bustimes_livery(api_livery_data)
                api_livery_left_css = livery_data["left_css"]
                api_livery_right_css = livery_data["right_css"]
                
                current_left_css = vehicle.livery.left_css or ""
                current_right_css = vehicle.livery.right_css or ""
                
                try:
                    minified_current_left = Livery.minify(current_left_css) if current_left_css else ""
                    minified_current_right = Livery.minify(current_right_css) if current_right_css else ""
                    minified_api_left = Livery.minify(api_livery_left_css) if api_livery_left_css else ""
                    minified_api_right = Livery.minify(api_livery_right_css) if api_livery_right_css else ""
                    
                    if minified_current_left == minified_api_left and minified_current_right == minified_api_right:
                        score += 5  # High weight for CSS match
                except Exception:
                    pass
            
            # Match by garage name
            api_garage_data = data.get("garage")
            if api_garage_data and vehicle.garage:
                if isinstance(api_garage_data, dict):
                    api_garage_name = compact_text(api_garage_data.get("name"))
                else:
                    api_garage_name = compact_text(api_garage_data)
                
                if api_garage_name and vehicle.garage.name == api_garage_name:
                    score += 2
            
            # Match by vehicle type name
            api_vehicle_type = data.get("vehicle_type")
            if api_vehicle_type and vehicle.vehicle_type:
                if isinstance(api_vehicle_type, dict):
                    api_vehicle_type_name = compact_text(api_vehicle_type.get("name"))
                else:
                    api_vehicle_type_name = compact_text(api_vehicle_type)
                
                if api_vehicle_type_name and vehicle.vehicle_type.name == api_vehicle_type_name:
                    score += 2
            
            # Match by feature names
            api_special_features = data.get("special_features")
            if api_special_features and isinstance(api_special_features, list):
                current_features_set = set(feature.name for feature in vehicle.features.all())
                api_features_set = set(compact_text(f) for f in api_special_features if f)
                
                if current_features_set == api_features_set:
                    score += 3
                elif current_features_set & api_features_set:  # Partial match
                    score += 1
            
            if score > best_match_score:
                best_match = data
                best_match_score = score
        
        if not best_match:
            return None  # No suitable match found
        
        data = best_match
        
        # If CSS doesn't match or vehicle has no livery, check all other fields
        differences = {}
        
        # Check fleet number
        if self._should_check_field("fleet_number"):
            api_fleet_number = data.get("fleet_number") or data.get("fleet_code")
            if api_fleet_number:
                try:
                    api_fleet_number = int(str(api_fleet_number))
                except (ValueError, TypeError):
                    api_fleet_number = None
                
                if api_fleet_number and vehicle.fleet_number != api_fleet_number:
                    differences["fleet_number"] = {
                        "current": vehicle.fleet_number,
                        "api": api_fleet_number,
                    }

        # Check operator (but not Stagecoach since we already skipped those)
        if api_operator_noc:
            api_operator_noc = compact_text(api_operator_noc)
            if vehicle.operator and vehicle.operator.noc.lower() != api_operator_noc.lower():
                differences["operator"] = {
                    "current": vehicle.operator.noc if vehicle.operator else None,
                    "api": api_operator_noc,
                }

        # Check name
        api_name = compact_text(data.get("name"))
        if api_name and vehicle.name != api_name:
            differences["name"] = {
                "current": vehicle.name,
                "api": api_name,
            }

        # Check garage (code and name)
        api_garage_data = data.get("garage")
        if api_garage_data:
            if isinstance(api_garage_data, dict):
                api_garage_code = compact_text(api_garage_data.get("code"))
                api_garage_name = compact_text(api_garage_data.get("name"))
            else:
                api_garage_code = compact_text(api_garage_data)
                api_garage_name = ""

            garage_differences = {}
            
            if vehicle.garage:
                if vehicle.garage.code != api_garage_code:
                    garage_differences["code"] = {
                        "current": vehicle.garage.code,
                        "api": api_garage_code,
                    }
                if vehicle.garage.name != api_garage_name:
                    garage_differences["name"] = {
                        "current": vehicle.garage.name,
                        "api": api_garage_name,
                    }
            else:
                # Vehicle has no garage but API does
                garage_differences = {
                    "code": {"current": None, "api": api_garage_code},
                    "name": {"current": None, "api": api_garage_name},
                }

            if garage_differences:
                differences["garage"] = garage_differences

        # Check external_id (Bustimes ID)
        api_id = data.get("id")
        if api_id:
            api_id_str = str(api_id)
            current_id = vehicle.external_id
            if current_id != api_id_str:
                differences["external_id"] = {
                    "current": current_id,
                    "api": api_id_str,
                }

        # Check slug
        api_slug = compact_text(data.get("slug"))
        if api_slug and vehicle.slug != api_slug:
            differences["slug"] = {
                "current": vehicle.slug,
                "api": api_slug,
            }

        # Check reg
        api_reg = compact_registration(data.get("reg"))
        if api_reg:
            current_reg = compact_registration(vehicle.reg)
            if current_reg != api_reg:
                differences["reg"] = {
                    "current": current_reg,
                    "api": api_reg,
                }

        # Check previous_reg
        api_previous_reg = compact_registration(data.get("previous_reg"))
        if api_previous_reg is not None:
            current_previous_reg = compact_registration(vehicle.prev_registration)
            if current_previous_reg != api_previous_reg:
                differences["prev_registration"] = {
                    "current": current_previous_reg,
                    "api": api_previous_reg,
                }

        # Check vehicle_type
        if self._should_check_field("vehicle_type"):
            api_vehicle_type = data.get("vehicle_type")
            if api_vehicle_type and isinstance(api_vehicle_type, dict):
                vehicle_type_differences = {}
                
                api_vehicle_type_name = compact_text(api_vehicle_type.get("name"))
                api_vehicle_type_style = compact_text(api_vehicle_type.get("style"))
                api_vehicle_type_fuel = compact_text(api_vehicle_type.get("fuel"))
                
                if vehicle.vehicle_type:
                    if vehicle.vehicle_type.name != api_vehicle_type_name:
                        vehicle_type_differences["name"] = {
                            "current": vehicle.vehicle_type.name,
                            "api": api_vehicle_type_name,
                        }
                    if vehicle.vehicle_type.style != api_vehicle_type_style:
                        vehicle_type_differences["style"] = {
                            "current": vehicle.vehicle_type.style,
                            "api": api_vehicle_type_style,
                        }
                    if vehicle.vehicle_type.fuel != api_vehicle_type_fuel:
                        vehicle_type_differences["fuel"] = {
                            "current": vehicle.vehicle_type.fuel,
                            "api": api_vehicle_type_fuel,
                        }
                else:
                    # Vehicle has no vehicle_type but API does
                    vehicle_type_differences = {
                        "name": {"current": None, "api": api_vehicle_type_name},
                        "style": {"current": None, "api": api_vehicle_type_style},
                        "fuel": {"current": None, "api": api_vehicle_type_fuel},
                    }

                if vehicle_type_differences:
                    differences["vehicle_type"] = vehicle_type_differences

        # Check branding
        api_branding = compact_text(data.get("branding"))
        if api_branding is not None and vehicle.branding != api_branding:
            differences["branding"] = {
                "current": vehicle.branding,
                "api": api_branding,
            }

        # Check notes
        api_notes = compact_text(data.get("notes"))
        if api_notes is not None and vehicle.notes != api_notes:
            differences["notes"] = {
                "current": vehicle.notes,
                "api": api_notes,
            }

        # Check withdrawn
        api_withdrawn = data.get("withdrawn")
        if api_withdrawn is not None and vehicle.withdrawn != api_withdrawn:
            differences["withdrawn"] = {
                "current": vehicle.withdrawn,
                "api": api_withdrawn,
            }

        # Check special_features
        api_special_features = data.get("special_features")
        if api_special_features is not None:
            if isinstance(api_special_features, list):
                api_features_set = set(compact_text(f) for f in api_special_features if f)
            else:
                api_features_set = set()
            
            current_features_set = set(feature.name for feature in vehicle.features.all())
            
            if current_features_set != api_features_set:
                differences["special_features"] = {
                    "current": sorted(current_features_set) if current_features_set else [],
                    "api": sorted(api_features_set) if api_features_set else [],
                }

        # Check livery (name and CSS)
        if self._should_check_field("livery"):
            if api_livery_data:
                livery_data = normalise_bustimes_livery(api_livery_data)
            api_livery_name = livery_data["name"]
            api_livery_left_css = livery_data["left_css"]
            api_livery_right_css = livery_data["right_css"]

            livery_differences = {}
            
            if vehicle.livery:
                if vehicle.livery.name != api_livery_name:
                    livery_differences["name"] = {
                        "current": vehicle.livery.name,
                        "api": api_livery_name,
                    }
                
                # Check exact CSS (compare minified versions)
                current_left_css = vehicle.livery.left_css or ""
                current_right_css = vehicle.livery.right_css or ""
                
                # Try to minify current CSS for comparison
                try:
                    minified_current_left = Livery.minify(current_left_css) if current_left_css else ""
                except Exception:
                    minified_current_left = current_left_css
                
                try:
                    minified_current_right = Livery.minify(current_right_css) if current_right_css else ""
                except Exception:
                    minified_current_right = current_right_css
                
                # Try to minify API CSS for comparison
                try:
                    minified_api_left = Livery.minify(api_livery_left_css) if api_livery_left_css else ""
                except Exception:
                    minified_api_left = api_livery_left_css
                
                try:
                    minified_api_right = Livery.minify(api_livery_right_css) if api_livery_right_css else ""
                except Exception:
                    minified_api_right = api_livery_right_css
                
                if minified_current_left != minified_api_left:
                    livery_differences["left_css"] = {
                        "current": current_left_css,
                        "api": api_livery_left_css,
                    }
                
                if minified_current_right != minified_api_right:
                    livery_differences["right_css"] = {
                        "current": current_right_css,
                        "api": api_livery_right_css,
                    }
            else:
                # Vehicle has no livery but API does
                livery_differences = {
                    "name": {"current": None, "api": api_livery_name},
                    "left_css": {"current": None, "api": api_livery_left_css},
                    "right_css": {"current": None, "api": api_livery_right_css},
                }

            if livery_differences:
                differences["livery"] = livery_differences

        if differences:
            return {"vehicle": vehicle, "differences": differences, "api_data": data}
        
        return None

    def _check_vehicle_from_map(self, vehicle, bustimes_vehicles_map):
        from busstops.management.commands._sync_bustimes import normalise_bustimes_livery
        
        # Try to find the vehicle in the lookup map by various identifiers
        data = None
        
        # Try by registration
        if vehicle.reg:
            reg = compact_registration(vehicle.reg)
            data = bustimes_vehicles_map.get(reg)
        
        # Try by fleet code
        if not data and vehicle.fleet_code:
            fleet_code = compact_text(vehicle.fleet_code)
            data = bustimes_vehicles_map.get(fleet_code)
        
        # Try by code
        if not data and vehicle.code:
            code = compact_text(vehicle.code)
            data = bustimes_vehicles_map.get(code)

        if not data:
            return None

        differences = {}
        
        # Check fleet number
        api_fleet_number = data.get("fleet_number") or data.get("fleet_code")
        if api_fleet_number:
            try:
                api_fleet_number = int(str(api_fleet_number))
            except (ValueError, TypeError):
                api_fleet_number = None
            
            if api_fleet_number and vehicle.fleet_number != api_fleet_number:
                differences["fleet_number"] = {
                    "current": vehicle.fleet_number,
                    "api": api_fleet_number,
                }

        # Check operator
        api_operator_noc = None
        if data.get("operator"):
            if isinstance(data["operator"], dict):
                api_operator_noc = data["operator"].get("noc") or data["operator"].get("id")
            else:
                api_operator_noc = data["operator"]
        
        if api_operator_noc:
            api_operator_noc = compact_text(api_operator_noc)
            if vehicle.operator and vehicle.operator.noc.lower() != api_operator_noc.lower():
                differences["operator"] = {
                    "current": vehicle.operator.noc if vehicle.operator else None,
                    "api": api_operator_noc,
                }

        # Check name
        api_name = compact_text(data.get("name"))
        if api_name and vehicle.name != api_name:
            differences["name"] = {
                "current": vehicle.name,
                "api": api_name,
            }

        # Check garage (code and name)
        api_garage_data = data.get("garage")
        if api_garage_data:
            if isinstance(api_garage_data, dict):
                api_garage_code = compact_text(api_garage_data.get("code"))
                api_garage_name = compact_text(api_garage_data.get("name"))
            else:
                api_garage_code = compact_text(api_garage_data)
                api_garage_name = ""

            garage_differences = {}
            
            if vehicle.garage:
                if vehicle.garage.code != api_garage_code:
                    garage_differences["code"] = {
                        "current": vehicle.garage.code,
                        "api": api_garage_code,
                    }
                if vehicle.garage.name != api_garage_name:
                    garage_differences["name"] = {
                        "current": vehicle.garage.name,
                        "api": api_garage_name,
                    }
            else:
                # Vehicle has no garage but API does
                garage_differences = {
                    "code": {"current": None, "api": api_garage_code},
                    "name": {"current": None, "api": api_garage_name},
                }

            if garage_differences:
                differences["garage"] = garage_differences

        # Check external_id (Bustimes ID)
        api_id = data.get("id")
        if api_id:
            api_id_str = str(api_id)
            current_id = vehicle.external_id
            if current_id != api_id_str:
                differences["external_id"] = {
                    "current": current_id,
                    "api": api_id_str,
                }

        # Check slug
        api_slug = compact_text(data.get("slug"))
        if api_slug and vehicle.slug != api_slug:
            differences["slug"] = {
                "current": vehicle.slug,
                "api": api_slug,
            }

        # Check reg
        api_reg = compact_registration(data.get("reg"))
        if api_reg:
            current_reg = compact_registration(vehicle.reg)
            if current_reg != api_reg:
                differences["reg"] = {
                    "current": current_reg,
                    "api": api_reg,
                }

        # Check previous_reg
        api_previous_reg = compact_registration(data.get("previous_reg"))
        if api_previous_reg is not None:
            current_previous_reg = compact_registration(vehicle.prev_registration)
            if current_previous_reg != api_previous_reg:
                differences["prev_registration"] = {
                    "current": current_previous_reg,
                    "api": api_previous_reg,
                }

        # Check vehicle_type
        if self._should_check_field("vehicle_type"):
            api_vehicle_type = data.get("vehicle_type")
            if api_vehicle_type and isinstance(api_vehicle_type, dict):
                vehicle_type_differences = {}
                
                api_vehicle_type_name = compact_text(api_vehicle_type.get("name"))
                api_vehicle_type_style = compact_text(api_vehicle_type.get("style"))
                api_vehicle_type_fuel = compact_text(api_vehicle_type.get("fuel"))
                
                if vehicle.vehicle_type:
                    if vehicle.vehicle_type.name != api_vehicle_type_name:
                        vehicle_type_differences["name"] = {
                            "current": vehicle.vehicle_type.name,
                            "api": api_vehicle_type_name,
                        }
                    if vehicle.vehicle_type.style != api_vehicle_type_style:
                        vehicle_type_differences["style"] = {
                            "current": vehicle.vehicle_type.style,
                            "api": api_vehicle_type_style,
                        }
                    if vehicle.vehicle_type.fuel != api_vehicle_type_fuel:
                        vehicle_type_differences["fuel"] = {
                            "current": vehicle.vehicle_type.fuel,
                            "api": api_vehicle_type_fuel,
                        }
                else:
                    # Vehicle has no vehicle_type but API does
                    vehicle_type_differences = {
                        "name": {"current": None, "api": api_vehicle_type_name},
                        "style": {"current": None, "api": api_vehicle_type_style},
                        "fuel": {"current": None, "api": api_vehicle_type_fuel},
                    }

                if vehicle_type_differences:
                    differences["vehicle_type"] = vehicle_type_differences

        # Check branding
        api_branding = compact_text(data.get("branding"))
        if api_branding is not None and vehicle.branding != api_branding:
            differences["branding"] = {
                "current": vehicle.branding,
                "api": api_branding,
            }

        # Check notes
        api_notes = compact_text(data.get("notes"))
        if api_notes is not None and vehicle.notes != api_notes:
            differences["notes"] = {
                "current": vehicle.notes,
                "api": api_notes,
            }

        # Check withdrawn
        api_withdrawn = data.get("withdrawn")
        if api_withdrawn is not None and vehicle.withdrawn != api_withdrawn:
            differences["withdrawn"] = {
                "current": vehicle.withdrawn,
                "api": api_withdrawn,
            }

        # Check special_features
        api_special_features = data.get("special_features")
        if api_special_features is not None:
            if isinstance(api_special_features, list):
                api_features_set = set(compact_text(f) for f in api_special_features if f)
            else:
                api_features_set = set()
            
            current_features_set = set(feature.name for feature in vehicle.features.all())
            
            if current_features_set != api_features_set:
                differences["special_features"] = {
                    "current": sorted(current_features_set) if current_features_set else [],
                    "api": sorted(api_features_set) if api_features_set else [],
                }

        # Check livery (exact CSS and name)
        api_livery_data = data.get("livery")
        if api_livery_data:
            # Use normalise_bustimes_livery to properly normalize the data
            livery_data = normalise_bustimes_livery(api_livery_data)
            api_livery_name = livery_data["name"]
            api_livery_left_css = livery_data["left_css"]
            api_livery_right_css = livery_data["right_css"]

            livery_differences = {}
            
            if vehicle.livery:
                if vehicle.livery.name != api_livery_name:
                    livery_differences["name"] = {
                        "current": vehicle.livery.name,
                        "api": api_livery_name,
                    }
                
                # Check exact CSS (compare minified versions)
                current_left_css = vehicle.livery.left_css or ""
                current_right_css = vehicle.livery.right_css or ""
                
                # Try to minify current CSS for comparison
                try:
                    minified_current_left = Livery.minify(current_left_css) if current_left_css else ""
                except Exception:
                    minified_current_left = current_left_css
                
                try:
                    minified_current_right = Livery.minify(current_right_css) if current_right_css else ""
                except Exception:
                    minified_current_right = current_right_css
                
                # Try to minify API CSS for comparison
                try:
                    minified_api_left = Livery.minify(api_livery_left_css) if api_livery_left_css else ""
                except Exception:
                    minified_api_left = api_livery_left_css
                
                try:
                    minified_api_right = Livery.minify(api_livery_right_css) if api_livery_right_css else ""
                except Exception:
                    minified_api_right = api_livery_right_css
                
                if minified_current_left != minified_api_left:
                    livery_differences["left_css"] = {
                        "current": current_left_css,
                        "api": api_livery_left_css,
                    }
                
                if minified_current_right != minified_api_right:
                    livery_differences["right_css"] = {
                        "current": current_right_css,
                        "api": api_livery_right_css,
                    }
            else:
                # Vehicle has no livery but API does
                livery_differences = {
                    "name": {"current": None, "api": api_livery_name},
                    "left_css": {"current": None, "api": api_livery_left_css},
                    "right_css": {"current": None, "api": api_livery_right_css},
                }

            if livery_differences:
                differences["livery"] = livery_differences

        if differences:
            return {"vehicle": vehicle, "differences": differences, "api_data": data}
        
        return None

    def _write_preview(self, results, failures, skipped_stagecoach=0):
        if not results and not failures and skipped_stagecoach == 0:
            return

        self.stdout.write("\n" + "=" * 100)
        self.stdout.write("Differences found:")
        self.stdout.write("=" * 100)

        for result in results:
            vehicle = result["vehicle"]
            differences = result["differences"]
            label = vehicle.fleet_code or vehicle.fleet_number or vehicle.code
            self.stdout.write(f"\nVehicle: {label} ({vehicle.get_reg()})")
            
            for field, diff in differences.items():
                if field == "livery":
                    self.stdout.write(f"  Livery:")
                    for livery_field, livery_diff in diff.items():
                        current = livery_diff["current"] or "(none)"
                        api = livery_diff["api"] or "(none)"
                        self.stdout.write(f"    {livery_field}: {current} -> {api}")
                elif field == "garage":
                    self.stdout.write(f"  Garage:")
                    for garage_field, garage_diff in diff.items():
                        current = garage_diff["current"] or "(none)"
                        api = garage_diff["api"] or "(none)"
                        self.stdout.write(f"    {garage_field}: {current} -> {api}")
                elif field == "vehicle_type":
                    self.stdout.write(f"  Vehicle Type:")
                    for vt_field, vt_diff in diff.items():
                        current = vt_diff["current"] or "(none)"
                        api = vt_diff["api"] or "(none)"
                        self.stdout.write(f"    {vt_field}: {current} -> {api}")
                elif field == "special_features":
                    current = ", ".join(diff["current"]) if diff["current"] else "(none)"
                    api = ", ".join(diff["api"]) if diff["api"] else "(none)"
                    self.stdout.write(f"  special_features: {current} -> {api}")
                else:
                    current = diff["current"] or "(none)"
                    api = diff["api"] or "(none)"
                    self.stdout.write(f"  {field}: {current} -> {api}")

        if failures:
            self.stdout.write("\n" + "-" * 100)
            self.stdout.write("API lookup failures:")
            for vehicle, error in failures:
                label = vehicle.fleet_code or vehicle.fleet_number or vehicle.code
                self.stdout.write(f"- {label} ({vehicle.get_reg()}): {error}")

        if skipped_stagecoach > 0:
            self.stdout.write("\n" + "-" * 100)
            self.stdout.write(f"Skipped {skipped_stagecoach} vehicle(s) with Stagecoach operator.")

        self.stdout.write("\n" + "=" * 100)
        self.stdout.write(f"Total: {len(results)} vehicle(s) with differences, {len(failures)} failure(s), {skipped_stagecoach} skipped (Stagecoach).")
        self.stdout.write("=" * 100 + "\n")

    def _confirm_apply(self) -> bool:
        try:
            answer = input("Apply these changes? [y/N]: ")
        except EOFError:
            return False
        return answer.strip().lower() in {"y", "yes"}

    def _apply_updates(self, results, override=False):
        from busstops.management.commands._sync_bustimes import resolve_operator, resolve_livery, resolve_garage, resolve_or_create_garage
        from busstops.management.commands._sync_bustimes import resolve_vehicle_type
        from vehicles.models import VehicleFeature

        applied = 0
        failures = []

        for result in tqdm(results, desc="Applying updates", unit="vehicle", file=self.stdout):
            vehicle = result["vehicle"]
            differences = result["differences"]
            api_data = result["api_data"]

            try:
                if "fleet_number" in differences:
                    vehicle.fleet_number = differences["fleet_number"]["api"]
                    vehicle.fleet_code = str(differences["fleet_number"]["api"])

                if "operator" in differences:
                    new_operator = resolve_operator(differences["operator"]["api"])
                    if new_operator:
                        vehicle.operator = new_operator

                if "name" in differences:
                    vehicle.name = differences["name"]["api"]

                if "garage" in differences or api_data.get("garage"):
                    # Always create or resolve garage and apply operator
                    new_garage = resolve_or_create_garage(api_data.get("garage"), operator=vehicle.operator)
                    if new_garage:
                        vehicle.garage = new_garage
                        # Apply operator to garage if not already set
                        if new_garage.operator != vehicle.operator and vehicle.operator:
                            new_garage.operator = vehicle.operator
                            new_garage.save()

                if "livery" in differences:
                    # Apply livery if field is being synced (via --fields) or override is set
                    if override or (self.fields_to_check and "livery" in self.fields_to_check):
                        new_livery = resolve_livery(api_data.get("livery"))
                        if new_livery:
                            vehicle.livery = new_livery

                if "external_id" in differences:
                    vehicle.external_id = differences["external_id"]["api"]

                if "slug" in differences:
                    vehicle.slug = differences["slug"]["api"]

                # Always reapply registration from API data to ensure it's current
                if "reg" in differences or api_data.get("reg"):
                    vehicle.reg = differences.get("reg", {}).get("api") or compact_registration(api_data.get("reg"))

                if "prev_registration" in differences:
                    vehicle.prev_registration = differences["prev_registration"]["api"]

                if "vehicle_type" in differences:
                    # Apply vehicle type if field is being synced (via --fields) or override is set
                    if override or (self.fields_to_check and "vehicle_type" in self.fields_to_check):
                        new_vehicle_type = resolve_vehicle_type(api_data.get("vehicle_type"))
                        if new_vehicle_type:
                            vehicle.vehicle_type = new_vehicle_type

                if "branding" in differences:
                    vehicle.branding = differences["branding"]["api"]

                if "notes" in differences:
                    vehicle.notes = differences["notes"]["api"]

                if "withdrawn" in differences:
                    vehicle.withdrawn = differences["withdrawn"]["api"]

                if "special_features" in differences and override:
                    api_features = differences["special_features"]["api"]
                    vehicle.features.clear()
                    for feature_name in api_features:
                        feature, _ = VehicleFeature.objects.get_or_create(name=feature_name)
                        vehicle.features.add(feature)

                vehicle.save()
                applied += 1
            except Exception as exc:
                label = vehicle.fleet_code or vehicle.fleet_number or vehicle.code
                failures.append((label, vehicle.get_reg(), str(exc)))
                continue

        self.stdout.write(self.style.SUCCESS(f"Applied changes to {applied} vehicle(s)."))

        if failures:
            self.stdout.write(self.style.WARNING(f"\nFailed to update {len(failures)} vehicle(s):"))
            for label, reg, error in failures:
                self.stdout.write(f"  - {label} ({reg}): {error}")
