# Generated migration for RouteWaypoint model

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('bustimes', '0017_remove_route_event_end_date_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='RouteWaypoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('latitude', models.FloatField(help_text='Waypoint latitude coordinate')),
                ('longitude', models.FloatField(help_text='Waypoint longitude coordinate')),
                ('order', models.PositiveSmallIntegerField(help_text='Order of this waypoint within the segment (0, 1, 2, ...)')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('modified_at', models.DateTimeField(auto_now=True)),
                ('route_link', models.ForeignKey(
                    help_text='The route segment this waypoint belongs to',
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='waypoints',
                    to='bustimes.routelink'
                )),
            ],
            options={
                'unique_together': {('route_link', 'order')},
                'ordering': ('route_link', 'order'),
                'indexes': [
                    models.Index(fields=['route_link', 'order'], name='bustimes_route_link_order_idx'),
                ],
            },
        ),
    ]
