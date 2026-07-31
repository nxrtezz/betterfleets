from django.core.management.base import BaseCommand
from django.utils.text import slugify

from busstops.fields import generate_unique_slug
from busstops.models import Operator, Service, operator_slug_source, service_slug_source


def rebuild_slug(instance, source_value):
    field = instance._meta.get_field("slug")
    base_slug = slugify(source_value) or slugify(str(instance.pk or "item")) or "item"
    return generate_unique_slug(field, instance, base_slug, None)


class Command(BaseCommand):
    help = "Repair slugs accidentally saved from bound method repr values."

    def handle(self, *args, **options):
        repaired = 0

        for operator in Operator.objects.filter(slug__startswith="bound-method-"):
            operator.slug = rebuild_slug(operator, operator_slug_source(operator))
            operator.save(update_fields=["slug"])
            repaired += 1

        for service in Service.objects.filter(slug__startswith="bound-method-"):
            service.slug = rebuild_slug(service, service_slug_source(service))
            service.save(update_fields=["slug"])
            repaired += 1

        self.stdout.write(self.style.SUCCESS(f"Repaired {repaired} broken slugs"))
