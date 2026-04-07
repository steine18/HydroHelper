from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0007_stage_q_comparison_site'),
    ]

    operations = [
        migrations.AddField(
            model_name='analysisreport',
            name='prior_period_analysis',
            field=models.TextField(
                blank=True,
                help_text="Optional: paste the previous period's analysis text here to use as style reference in the Copilot prompt export.",
            ),
        ),
    ]
