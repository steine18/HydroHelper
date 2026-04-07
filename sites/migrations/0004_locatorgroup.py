from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('usgs_sites', '0003_move_schedule_to_site'),
    ]

    operations = [
        # 1. Create LocatorGroup table
        migrations.CreateModel(
            name='LocatorGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, unique=True)),
                ('transmit_interval_hours', models.PositiveSmallIntegerField(
                    blank=True, null=True,
                    help_text='Scheduled ALERT2 transmit interval in hours (e.g. 1, 4, 8).',
                )),
                ('transmit_offset_minutes', models.PositiveSmallIntegerField(
                    default=0,
                    help_text='Minutes offset within each interval.',
                )),
            ],
            options={
                'ordering': ['name'],
            },
        ),

        # 2. Remove old unique_together before altering site FK
        migrations.AlterUniqueTogether(
            name='novapointlocator',
            unique_together=set(),
        ),

        # 3. Make site nullable
        migrations.AlterField(
            model_name='novapointlocator',
            name='site',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='nova_point_locators',
                to='usgs_sites.site',
            ),
        ),

        # 4. Add group FK
        migrations.AddField(
            model_name='novapointlocator',
            name='group',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='nova_point_locators',
                to='usgs_sites.locatorgroup',
            ),
        ),

        # 5. Update ordering meta
        migrations.AlterModelOptions(
            name='novapointlocator',
            options={'ordering': ['parameter_type']},
        ),

        # 6. Re-add unique_together with both constraints
        migrations.AlterUniqueTogether(
            name='novapointlocator',
            unique_together={('site', 'point_locator'), ('group', 'point_locator')},
        ),
    ]
