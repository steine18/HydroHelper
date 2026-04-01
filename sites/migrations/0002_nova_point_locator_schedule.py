from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('usgs_sites', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='novapointlocator',
            name='transmit_interval_hours',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                help_text='Scheduled transmit interval in hours (e.g. 1, 4, 8). Leave blank if not scheduled.',
            ),
        ),
        migrations.AddField(
            model_name='novapointlocator',
            name='transmit_offset_minutes',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Minutes offset within each interval (e.g. 10 means transmits at :10 past each interval start).',
            ),
        ),
    ]
