from pathlib import Path
import io
import zipfile

from django.utils import timezone

from .management.commands.import_netex_fares import Command, get_existing_fare_zones
from .models import DataSet
from .netex_preview import parse_netex_preview


def build_dataset_identity(filename, source_identifier=None):
    if source_identifier:
        return source_identifier
    return f"https://local.invalid/netex-upload/{filename}"


def import_netex_file_object(uploaded_file, source_identifier=None):
    uploaded_file.seek(0)
    preview = parse_netex_preview(uploaded_file)
    uploaded_file.seek(0)

    filename = Path(getattr(uploaded_file, "name", "netex.xml")).name
    dataset_name = preview.get("frame_name") or filename
    dataset_description = preview.get("frame_description") or preview.get(
        "description", ""
    )
    dataset_url = build_dataset_identity(filename, source_identifier)

    dataset, _ = DataSet.objects.get_or_create(
        url=dataset_url,
        defaults={"name": dataset_name},
    )
    dataset.name = dataset_name
    dataset.description = dataset_description[:255]
    dataset.datetime = timezone.now()
    dataset.published = True
    dataset.save()
    dataset.tariff_set.all().delete()

    command = Command()
    command.user_profiles = {}
    command.sales_offer_packages = {}
    command.fare_products = {}
    command.fare_zones = get_existing_fare_zones(dataset)
    command.handle_file(dataset, uploaded_file, filename)

    operator_ids = (
        dataset.tariff_set.filter(operators__isnull=False)
        .values_list("operators__pk", flat=True)
        .distinct()
    )
    dataset.operators.set(operator_ids)
    dataset.save(update_fields=["name", "description", "datetime", "published"])
    return dataset, preview


def import_netex_path(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        return import_netex_archive(path)
    with path.open("rb") as open_file:
        return import_netex_file_object(
            open_file, source_identifier=path.resolve().as_uri()
        )


def import_netex_archive(path):
    path = Path(path)
    archive_source_identifier = path.resolve().as_uri()
    imported = []

    with zipfile.ZipFile(path) as archive:
        for member_name in archive.namelist():
            if member_name.endswith("/") or not member_name.lower().endswith(".xml"):
                continue
            with archive.open(member_name) as archived_file:
                payload = archived_file.read()
            dataset, preview = import_netex_file_object(
                io.BytesIO(payload),
                source_identifier=f"{archive_source_identifier}!/{member_name}",
            )
            imported.append((dataset, preview, member_name))

    return imported
