# Generated migration for BetterFleets changes - remove invitation system

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_m2m_through_models'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Invitation',
        ),
        migrations.DeleteModel(
            name='InvitationOperator',
        ),
    ]
