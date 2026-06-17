# Generated manually for Agent Action audit records.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0009_modelcalllog"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RagAgentAction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action_uid", models.CharField(max_length=160)),
                ("action_type", models.CharField(choices=[("create_regression_case", "Create Regression Case")], max_length=50)),
                ("source", models.CharField(blank=True, default="", max_length=50)),
                ("title", models.CharField(max_length=160)),
                ("description", models.TextField(blank=True, default="")),
                ("confirm_label", models.CharField(blank=True, default="Confirm", max_length=60)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed"), ("rejected", "Rejected")], default="pending", max_length=20)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
                ("rejected_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_case", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="agent_actions", to="rag.ragbenchmarkcase")),
                ("eval_case_result", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rag_agent_actions", to="rag.ragevalcaseresult")),
                ("eval_run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rag_agent_actions", to="rag.ragevalrun")),
                ("kb", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rag_agent_actions", to="rag.knowledgebase")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rag_agent_actions", to=settings.AUTH_USER_MODEL)),
                ("trace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rag_agent_actions", to="rag.ragtrace")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="ragagentaction",
            constraint=models.UniqueConstraint(fields=("owner", "action_uid"), name="unique_agent_action_per_owner"),
        ),
        migrations.AddIndex(
            model_name="ragagentaction",
            index=models.Index(fields=["owner", "status", "created_at"], name="rag_ragagen_owner_i_26e991_idx"),
        ),
        migrations.AddIndex(
            model_name="ragagentaction",
            index=models.Index(fields=["kb", "created_at"], name="rag_ragagen_kb_id_76cbb5_idx"),
        ),
        migrations.AddIndex(
            model_name="ragagentaction",
            index=models.Index(fields=["trace", "created_at"], name="rag_ragagen_trace_i_36f438_idx"),
        ),
        migrations.AddIndex(
            model_name="ragagentaction",
            index=models.Index(fields=["eval_run", "created_at"], name="rag_ragagen_eval_ru_284515_idx"),
        ),
    ]
