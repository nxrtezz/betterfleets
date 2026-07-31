import io
import zipfile

from lxml import etree

SIRI_NS = "http://www.siri.org.uk/siri"


def elem_to_dict(elem):
    children = list(elem)
    if not children:
        return elem.text
    result = {}
    for child in children:
        key = child.tag.split("}", 1)[1] if "}" in child.tag else child.tag
        value = elem_to_dict(child)
        existing = result.get(key)
        if existing is not None:
            if not isinstance(existing, list):
                result[key] = [existing]
            result[key].append(value)
        else:
            result[key] = value
    return result


def maybe_unzip_payload(data: bytes, content_type: str = "") -> bytes:
    if "application/zip" in content_type or zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if not names:
                return b""
            with archive.open(names[0]) as open_file:
                return open_file.read()
    return data


def parse_vehicle_activity_xml(data: bytes) -> tuple[etree._Element, list[dict]]:
    root = etree.fromstring(data)
    service_delivery = root.find(f"{{{SIRI_NS}}}ServiceDelivery")
    if service_delivery is None:
        return root, []

    delivery = service_delivery.find(f"{{{SIRI_NS}}}VehicleMonitoringDelivery")
    if delivery is None:
        return root, []

    return root, [
        elem_to_dict(activity)
        for activity in delivery.findall(f"{{{SIRI_NS}}}VehicleActivity")
    ]
