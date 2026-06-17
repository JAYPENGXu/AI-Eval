# Generated manually for user feedback weak signals.

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0010_ragagentaction"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RagUserFeedback",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rating", models.CharField(choices=[("helpful", "Helpful"), ("not_helpful", "Not Helpful")], max_length=20)),
                ("reason", models.CharField(blank=True, choices=[("missed_question", "Missed Question"), ("wrong_citation", "Wrong Citation"), ("insufficient_context", "Insufficient Context"), ("off_topic", "Off Topic"), ("factual_error", "Factual Error"), ("too_verbose", "Too Verbose"), ("other", "Other")], default="", max_length=40)),
                ("comment", models.TextField(blank=True, default="")),
                ("failure_signals", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_action", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="user_feedback_items", to="rag.ragagentaction")),
                ("kb", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rag_user_feedback", to="rag.knowledgebase")),
                ("message", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feedback", to="rag.chatmessage")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rag_user_feedback", to=settings.AUTH_USER_MODEL)),
                ("session", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="feedback", to="rag.chatsession")),
                ("trace", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="user_feedback", to="rag.ragtrace")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="raguserfeedback",
            constraint=models.UniqueConstraint(fields=("owner", "message"), name="unique_feedback_per_user_message"),
        ),
        migrations.AddIndex(
            model_name="raguserfeedback",
            index=models.Index(fields=["owner", "created_at"], name="rag_raguser_owner_i_3a5aa5_idx"),
        ),
        migrations.AddIndex(
            model_name="raguserfeedback",
            index=models.Index(fields=["kb", "rating", "created_at"], name="rag_raguser_kb_id_c2ed12_idx"),
        ),
        migrations.AddIndex(
            model_name="raguserfeedback",
            index=models.Index(fields=["trace", "rating"], name="rag_raguser_trace_i_f39d0e_idx"),
        ),
    ]
