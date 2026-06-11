from django.conf import settings
from django.db import models
from django.utils import timezone


class KnowledgeBase(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    STATUS_CHOICES = [
        ("uploaded", "Uploaded"),
        ("chunked", "Chunked"),
        ("indexed", "Indexed"),
        ("failed", "Failed"),
    ]

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    file_type = models.CharField(max_length=50, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="uploaded")
    chunk_method = models.CharField(max_length=50, default="sentence")
    chunk_options = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.filename


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="chunks")
    index = models.PositiveIntegerField()
    content = models.TextField()
    token_count = models.PositiveIntegerField(default=0)
    embedding = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["document_id", "index"]


class ChatSession(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE)
    title = models.CharField(max_length=120, default="新会话")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


class ChatMessage(models.Model):
    ROLE_CHOICES = [("user", "User"), ("assistant", "Assistant")]

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]


class RagTrace(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="traces")
    message = models.OneToOneField(ChatMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="trace")
    question = models.TextField()
    rewritten_query = models.TextField(blank=True, default="")
    retrieval_mode = models.CharField(max_length=50, default="vector")
    vector_results = models.JSONField(default=list, blank=True)
    bm25_results = models.JSONField(default=list, blank=True)
    hybrid_results = models.JSONField(default=list, blank=True)
    rerank_results = models.JSONField(default=list, blank=True)
    compression_results = models.JSONField(default=list, blank=True)
    compression_stats = models.JSONField(default=dict, blank=True)
    original_context = models.TextField(blank=True, default="")
    compressed_context = models.TextField(blank=True, default="")
    final_prompt = models.TextField(blank=True, default="")
    settings = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class RagBenchmarkCase(models.Model):
    DIFFICULTY_CHOICES = [
        ("easy", "Easy"),
        ("medium", "Medium"),
        ("hard", "Hard"),
    ]
    SUITE_CHOICES = [
        ("smoke", "Smoke"),
        ("benchmark", "Benchmark"),
        ("regression", "Regression"),
        ("release", "Release"),
    ]
    SOURCE_CHOICES = [
        ("expert", "Expert"),
        ("trace", "Trace"),
        ("eval_failure", "Eval Failure"),
        ("user_feedback", "User Feedback"),
        ("default_json", "Default JSON"),
    ]

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="benchmark_cases")
    case_id = models.CharField(max_length=120)
    question = models.TextField()
    reference = models.TextField()
    tags = models.JSONField(default=list, blank=True)
    expected_terms = models.JSONField(default=list, blank=True)
    target_chunk_ids = models.JSONField(default=list, blank=True)
    suite = models.CharField(max_length=30, choices=SUITE_CHOICES, default="benchmark")
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default="expert")
    notes = models.TextField(blank=True, default="")
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default="medium")
    enabled = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["case_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["kb", "case_id"], name="unique_benchmark_case_per_kb"),
        ]

    def __str__(self):
        return self.case_id


class RagEvalRun(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="eval_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    metrics = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    mean_scores = models.JSONField(default=dict, blank=True)
    retrieval_metrics = models.JSONField(default=dict, blank=True)
    case_count = models.PositiveIntegerField(default=0)
    cases_path = models.CharField(max_length=500, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class RagEvalCaseResult(models.Model):
    run = models.ForeignKey(RagEvalRun, on_delete=models.CASCADE, related_name="case_results")
    case_id = models.CharField(max_length=120)
    question = models.TextField()
    reference = models.TextField(blank=True, default="")
    answer = models.TextField(blank=True, default="")
    rewritten_query = models.TextField(blank=True, default="")
    rewrite_strategy = models.CharField(max_length=50, blank=True, default="")
    contexts = models.JSONField(default=list, blank=True)
    scores = models.JSONField(default=dict, blank=True)
    compression_stats = models.JSONField(default=dict, blank=True)
    top_chunks = models.JSONField(default=dict, blank=True)
    diagnostics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]

class ModelCallLog(models.Model):
    STATUS_CHOICES = [
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]
    CALL_TYPE_CHOICES = [
        ("chat", "Chat"),
        ("embedding_index", "Embedding Index"),
        ("embedding_query", "Embedding Query"),
        ("rewrite", "Query Rewrite"),
        ("compression", "Compression"),
        ("rerank", "Rerank"),
        ("ragas", "RAGAS"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="model_call_logs")
    kb = models.ForeignKey(KnowledgeBase, null=True, blank=True, on_delete=models.SET_NULL, related_name="model_call_logs")
    session = models.ForeignKey(ChatSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="model_call_logs")
    message = models.ForeignKey(ChatMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="model_call_logs")
    trace = models.ForeignKey(RagTrace, null=True, blank=True, on_delete=models.SET_NULL, related_name="model_call_logs")
    eval_run = models.ForeignKey(RagEvalRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="model_call_logs")
    provider = models.CharField(max_length=80, blank=True, default="")
    model = models.CharField(max_length=120)
    call_type = models.CharField(max_length=40, choices=CALL_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="completed")
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    estimated_cost = models.FloatField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "created_at"]),
            models.Index(fields=["kb", "created_at"]),
            models.Index(fields=["trace", "created_at"]),
            models.Index(fields=["model", "call_type"]),
            models.Index(fields=["status", "latency_ms"]),
        ]

