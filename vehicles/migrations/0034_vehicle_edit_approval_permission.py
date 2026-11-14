from django.db import migrations


def create_group(apps, schema_editor):
    alias = schema_editor.connection.alias
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    content_type, _ = ContentType.objects.using(alias).get_or_create(app_label="vehicles", model="vehiclerevision")
    permission, _ = Permission.objects.using(alias).get_or_create(content_type=content_type, codename="approve_vehicle_edits", defaults={"name": "Approve and decline edits"})
    group, _ = Group.objects.using(alias).get_or_create(name="edits")
    group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0033_merge_20261111_1510"), ("auth", "0012_alter_user_first_name_max_length")]
    operations = [
        migrations.AlterModelOptions(name="vehiclerevision", options={"permissions": [("approve_vehicle_edits", "Approve and decline edits")]}),
        migrations.RunPython(create_group, migrations.RunPython.noop),
    ]
