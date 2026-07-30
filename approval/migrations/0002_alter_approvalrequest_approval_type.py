from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('approval', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='approvalrequest',
            name='approval_type',
            field=models.CharField(
                choices=[
                    ('stage_discharge', 'Stage/Discharge'),
                    ('auto_stage_discharge', 'Stage/Discharge Auto-Record'),
                    ('precipitation', 'Precipitation'),
                    ('groundwater', 'Groundwater'),
                ],
                max_length=50,
            ),
        ),
    ]
