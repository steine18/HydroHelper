from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rating_developer', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='ratingconfig',
            name='cross_site_configs',
            field=models.JSONField(
                default=list,
                help_text='List of {site_no, offset_minutes, label} dicts for cross-site measurement transfer.',
            ),
        ),
    ]
