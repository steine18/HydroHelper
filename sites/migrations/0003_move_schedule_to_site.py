from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0002_nova_point_locator_schedule'),
    ]

    operations = [
        # Add schedule fields to Site
        migrations.AddField(
            model_name='site',
            name='transmit_interval_hours',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                help_text='Scheduled ALERT2 transmit interval in hours (e.g. 1, 4, 8).',
            ),
        ),
        migrations.AddField(
            model_name='site',
            name='transmit_offset_minutes',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Minutes offset within each interval (e.g. 10 means transmits at :10 past each interval start).',
            ),
        ),
        # Remove schedule fields from NovaPointLocator
        migrations.RemoveField(
            model_name='novapointlocator',
            name='transmit_interval_hours',
        ),
        migrations.RemoveField(
            model_name='novapointlocator',
            name='transmit_offset_minutes',
        ),
    ]
