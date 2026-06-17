# Generated for first-pass LLM-as-Judge result persistence.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0016_expert_eval_case_schema"),
    ]

    operations = [
        migrations.AddField(
            model_name="ragevalcaseresult",
            name="judge_results",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
