# Generated for expert eval case schema upgrade.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0015_chatsessionsummary"),
    ]

    operations = [
        migrations.AddField(
            model_name="ragbenchmarkcase",
            name="case_type",
            field=models.CharField(choices=[("expert", "Expert"), ("regression", "Regression"), ("smoke", "Smoke"), ("release_gate", "Release Gate")], default="expert", max_length=40),
        ),
        migrations.AddField(
            model_name="ragbenchmarkcase",
            name="deterministic_checks",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="ragbenchmarkcase",
            name="rubric",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="ragbenchmarkcase",
            name="thresholds",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="ragevalcaseresult",
            name="case_type",
            field=models.CharField(blank=True, default="", max_length=40),
        ),
        migrations.AddField(
            model_name="ragevalcaseresult",
            name="suite",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
        migrations.AddField(
            model_name="ragevalcaseresult",
            name="deterministic_results",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
