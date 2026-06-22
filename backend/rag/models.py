import hashlib
import json

from django.conf import settings
from django.db import models
from django.utils import timezone


RAG_EVAL_SIGNATURE_KEYS = [
    "query_rewrite_strategy",
    "top_k",
    "bm25_top_k",
    "rrf_k",
    "rerank_top_n",
    "compression_strategy",
    "chat_model",
    "embedding_model",
    "embedding_dimensions",
]


def build_eval_param_payload(eval_settings):
    eval_settings = eval_settings or {}
    requested_options = eval_settings.get("requested_options") if isinstance(eval_settings, dict) else {}
    source = requested_options if isinstance(requested_options, dict) else {}
    defaults = {
        "query_rewrite_strategy": getattr(settings, "QUERY_REWRITE_STRATEGY", "rule"),
        "top_k": getattr(settings, "RAG_TOP_K", 5),
        "bm25_top_k": getattr(settings, "BM25_TOP_K", 5),
        "rrf_k": getattr(settings, "RRF_K", 60),
        "rerank_top_n": getattr(settings, "RERANK_TOP_N", 5),
        "compression_strategy": getattr(settings, "CONTEXT_COMPRESSION_STRATEGY", "structure_aware"),
        "chat_model": getattr(settings, "CHAT_MODEL", ""),
        "embedding_model": getattr(settings, "EMBEDDING_MODEL", ""),
        "embedding_dimensions": getattr(settings, "EMBEDDING_DIMENSIONS", ""),
    }
    payload = {}
    for key in RAG_EVAL_SIGNATURE_KEYS:
        value = source.get(key, eval_settings.get(key, defaults[key]))
        if key in {"top_k", "bm25_top_k", "rrf_k", "rerank_top_n", "embedding_dimensions"} and value not in (None, ""):
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
        payload[key] = value
    return payload


def build_eval_param_signature(eval_settings):
    payload = build_eval_param_payload(eval_settings)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


CLASSIFICATION_CHOICES = [
    ("public", "Public"), ("internal", "Internal"),
    ("confidential", "Confidential"), ("restricted", "Restricted"),
]
CLASSIFICATION_RANK = {value: index for index, (value, _) in enumerate(CLASSIFICATION_CHOICES)}
ROLE_CAPABILITIES = [
    "manage_organization", "manage_members", "manage_roles", "manage_knowledge_bases",
    "manage_documents", "manage_policies", "query", "view_traces", "run_evaluations", "use_agent",
]


class Organization(models.Model):
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, unique=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_organizations")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["name", "id"]
    def __str__(self):
        return self.name


class Role(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="roles")
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    capabilities = models.JSONField(default=list, blank=True)
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["organization_id", "name"]
        constraints = [models.UniqueConstraint(fields=["organization", "slug"], name="unique_role_slug_per_org")]
    def __str__(self):
        return f"{self.organization_id}:{self.slug}"


class Membership(models.Model):
    STATUS_CHOICES = [("active", "Active"), ("suspended", "Suspended")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="organization_memberships")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    department = models.CharField(max_length=120, blank=True, default="")
    clearance = models.CharField(max_length=20, choices=CLASSIFICATION_CHOICES, default="internal")
    roles = models.ManyToManyField(Role, related_name="memberships", blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["organization_id", "user_id"]
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="unique_membership_per_org_user")]
    def __str__(self):
        return f"{self.organization_id}:{self.user_id}"


class AccessPolicy(models.Model):
    VISIBILITY_CHOICES = [("organization", "Organization"), ("restricted", "Restricted")]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="access_policies")
    name = models.CharField(max_length=160)
    classification = models.CharField(max_length=20, choices=CLASSIFICATION_CHOICES, default="internal")
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="organization")
    allowed_roles = models.ManyToManyField(Role, related_name="access_policies", blank=True)
    allowed_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="allowed_access_policies", blank=True)
    denied_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="denied_access_policies", blank=True)
    allowed_departments = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_access_policies")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["organization_id", "name", "id"]
        constraints = [models.UniqueConstraint(fields=["organization", "name"], name="unique_policy_name_per_org")]
    def __str__(self):
        return f"{self.organization_id}:{self.name}"


class AuthorizationAuditLog(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="authorization_audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="authorization_audit_logs")
    membership = models.ForeignKey(Membership, null=True, blank=True, on_delete=models.SET_NULL, related_name="authorization_audit_logs")
    action = models.CharField(max_length=80)
    resource_type = models.CharField(max_length=80, blank=True, default="")
    resource_id = models.CharField(max_length=120, blank=True, default="")
    allowed = models.BooleanField(default=False)
    reason = models.CharField(max_length=240, blank=True, default="")
    scope_fingerprint = models.CharField(max_length=64, blank=True, default="", db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "created_at"]),
            models.Index(fields=["actor", "allowed", "created_at"]),
        ]


class KnowledgeBase(models.Model):
    VISIBILITY_CHOICES = [("private", "Private"), ("organization", "Organization"), ("restricted", "Restricted")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.CASCADE, related_name="knowledge_bases")
    access_policy = models.ForeignKey(AccessPolicy, null=True, blank=True, on_delete=models.PROTECT, related_name="knowledge_bases")
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="private")
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    active_config_version = models.ForeignKey(
        "RagConfigVersion", null=True, blank=True, on_delete=models.SET_NULL, related_name="active_for_knowledge_bases"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    STATUS_CHOICES = [
        ("uploaded", "Uploaded"),
        ("queued", "Queued"),
        ("parsing", "Parsing"),
        ("parsed", "Parsed"),
        ("needs_review", "Needs review"),
        ("indexing", "Indexing"),
        ("indexed", "Indexed"),
        ("failed", "Failed"),
    ]

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="documents")
    access_policy = models.ForeignKey(AccessPolicy, null=True, blank=True, on_delete=models.PROTECT, related_name="documents")
    inherits_policy = models.BooleanField(default=True)
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to="documents/%Y/%m/%d/")
    file_type = models.CharField(max_length=50, blank=True, default="")
    mime_type = models.CharField(max_length=120, blank=True, default="")
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="uploaded")
    chunk_method = models.CharField(max_length=50, default="sentence")
    chunk_options = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    index_signature = models.CharField(max_length=64, blank=True, default="", db_index=True)
    index_manifest = models.JSONField(default=dict, blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.filename


class DocumentParseRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("needs_review", "Needs review"),
        ("failed", "Failed"),
        ("superseded", "Superseded"),
    ]

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="parse_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    parser = models.CharField(max_length=50, blank=True, default="")
    parser_version = models.CharField(max_length=30, blank=True, default="")
    celery_task_id = models.CharField(max_length=100, blank=True, default="")
    provider_job_id = models.CharField(max_length=160, blank=True, default="")
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    quality_score = models.FloatField(null=True, blank=True)
    quality_metrics = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=80, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class DocumentIndexRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"), ("running", "Running"), ("completed", "Completed"),
        ("failed", "Failed"), ("superseded", "Superseded"),
    ]
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="index_runs")
    parse_run = models.ForeignKey(DocumentParseRun, on_delete=models.PROTECT, related_name="index_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    celery_task_id = models.CharField(max_length=100, blank=True, default="")
    chunk_method = models.CharField(max_length=50, default="sentence")
    chunk_options = models.JSONField(default=dict, blank=True)
    target_signature = models.CharField(max_length=64, blank=True, default="", db_index=True)
    target_manifest = models.JSONField(default=dict, blank=True)
    progress_current = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    chunk_count = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class DocumentPage(models.Model):
    EXTRACTION_CHOICES = [("native", "Native"), ("ocr", "OCR")]

    parse_run = models.ForeignKey(DocumentParseRun, on_delete=models.CASCADE, related_name="pages")
    page_number = models.PositiveIntegerField()
    extraction_method = models.CharField(max_length=20, choices=EXTRACTION_CHOICES, default="native")
    text = models.TextField(blank=True, default="")
    markdown = models.TextField(blank=True, default="")
    blocks = models.JSONField(default=list, blank=True)
    char_count = models.PositiveIntegerField(default=0)
    is_blank = models.BooleanField(default=False)
    metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["page_number"]
        constraints = [
            models.UniqueConstraint(fields=["parse_run", "page_number"], name="unique_parse_run_page")
        ]


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="chunks")
    access_policy = models.ForeignKey(AccessPolicy, null=True, blank=True, on_delete=models.PROTECT, related_name="chunks")
    inherits_policy = models.BooleanField(default=True)
    parse_run = models.ForeignKey(
        DocumentParseRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="chunks"
    )
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
    source_chunk_ids = models.JSONField(default=list, blank=True)
    source_policy_ids = models.JSONField(default=list, blank=True)
    authorization_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]


class ChatSessionSummary(models.Model):
    STATUS_CHOICES = [
        ("idle", "Idle"),
        ("queued", "Queued"),
        ("running", "Running"),
        ("failed", "Failed"),
    ]

    session = models.OneToOneField(ChatSession, on_delete=models.CASCADE, related_name="summary_state")
    summary = models.TextField(blank=True, default="")
    summary_message_count = models.PositiveIntegerField(default=0)
    covered_until_message = models.ForeignKey(
        ChatMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    token_estimate = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="idle")
    error_message = models.TextField(blank=True, default="")
    last_started_at = models.DateTimeField(null=True, blank=True)
    celery_task_id = models.CharField(max_length=100, blank=True, default="")
    retry_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]

    def __str__(self):
        return f"summary:{self.session_id}:{self.summary_message_count}"


class RagUserFeedback(models.Model):
    RATING_CHOICES = [
        ("helpful", "Helpful"),
        ("not_helpful", "Not Helpful"),
    ]
    REASON_CHOICES = [
        ("missed_question", "Missed Question"),
        ("wrong_citation", "Wrong Citation"),
        ("insufficient_context", "Insufficient Context"),
        ("off_topic", "Off Topic"),
        ("factual_error", "Factual Error"),
        ("too_verbose", "Too Verbose"),
        ("other", "Other"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rag_user_feedback")
    kb = models.ForeignKey(KnowledgeBase, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_user_feedback")
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="feedback")
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name="feedback")
    trace = models.ForeignKey("RagTrace", null=True, blank=True, on_delete=models.SET_NULL, related_name="user_feedback")
    rating = models.CharField(max_length=20, choices=RATING_CHOICES)
    reason = models.CharField(max_length=40, choices=REASON_CHOICES, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    failure_signals = models.JSONField(default=list, blank=True)
    created_action = models.ForeignKey("RagAgentAction", null=True, blank=True, on_delete=models.SET_NULL, related_name="user_feedback_items")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "message"], name="unique_feedback_per_user_message"),
        ]
        indexes = [
            models.Index(fields=["owner", "created_at"]),
            models.Index(fields=["kb", "rating", "created_at"]),
            models.Index(fields=["trace", "rating"]),
        ]

    def __str__(self):
        return f"{self.rating}:{self.message_id}"


class RagTrace(models.Model):
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="traces")
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_traces")
    access_scope_fingerprint = models.CharField(max_length=64, blank=True, default="", db_index=True)
    access_policy_ids = models.JSONField(default=list, blank=True)
    authorization_decision = models.JSONField(default=dict, blank=True)
    redaction_metadata = models.JSONField(default=dict, blank=True)
    message = models.OneToOneField(ChatMessage, null=True, blank=True, on_delete=models.SET_NULL, related_name="trace")
    question = models.TextField()
    rewritten_query = models.TextField(blank=True, default="")
    query_intent = models.CharField(max_length=40, blank=True, default="internal_knowledge", db_index=True)
    route_decision = models.CharField(max_length=60, blank=True, default="rag")
    route_reason = models.TextField(blank=True, default="")
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
    CASE_TYPE_CHOICES = [
        ("expert", "Expert"),
        ("regression", "Regression"),
        ("smoke", "Smoke"),
        ("release_gate", "Release Gate"),
        ("security_acl", "Security ACL"),
    ]
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
        ("security", "Security"),
    ]
    SOURCE_CHOICES = [
        ("expert", "Expert"),
        ("trace", "Trace"),
        ("eval_failure", "Eval Failure"),
        ("user_feedback", "User Feedback"),
        ("default_json", "Default JSON"),
    ]

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="benchmark_cases")
    principal_membership = models.ForeignKey(Membership, null=True, blank=True, on_delete=models.SET_NULL, related_name="security_benchmark_cases")
    forbidden_document_ids = models.JSONField(default=list, blank=True)
    forbidden_chunk_ids = models.JSONField(default=list, blank=True)
    expected_authorized_document_ids = models.JSONField(default=list, blank=True)
    case_id = models.CharField(max_length=120)
    case_type = models.CharField(max_length=40, choices=CASE_TYPE_CHOICES, default="expert")
    question = models.TextField()
    reference = models.TextField()
    tags = models.JSONField(default=list, blank=True)
    expected_terms = models.JSONField(default=list, blank=True)
    target_chunk_ids = models.JSONField(default=list, blank=True)
    suite = models.CharField(max_length=30, choices=SUITE_CHOICES, default="benchmark")
    deterministic_checks = models.JSONField(default=dict, blank=True)
    rubric = models.JSONField(default=dict, blank=True)
    thresholds = models.JSONField(default=dict, blank=True)
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
        ("queued", "Queued"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="eval_runs")
    baseline_run = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="derived_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    metrics = models.JSONField(default=list, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    param_signature = models.CharField(max_length=24, blank=True, default="", db_index=True)
    mean_scores = models.JSONField(default=dict, blank=True)
    retrieval_metrics = models.JSONField(default=dict, blank=True)
    case_count = models.PositiveIntegerField(default=0)
    cases_path = models.CharField(max_length=500, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    celery_task_id = models.CharField(max_length=100, blank=True, default="")
    retry_count = models.PositiveIntegerField(default=0)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    execution_metrics = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["kb", "param_signature", "created_at"]),
        ]

    def save(self, *args, **kwargs):
        self.param_signature = build_eval_param_signature(self.settings)
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "settings" in update_fields and "param_signature" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "param_signature"]
        super().save(*args, **kwargs)



class RagExperimentPlan(models.Model):
    STATUS_CHOICES = [
        ("pending_confirmation", "Pending Confirmation"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rag_experiment_plans")
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="experiment_plans")
    baseline_run = models.ForeignKey(RagEvalRun, on_delete=models.CASCADE, related_name="experiment_plans")
    winner_variant = models.ForeignKey("RagExperimentVariant", null=True, blank=True, on_delete=models.SET_NULL, related_name="winner_for_plans")
    goal = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending_confirmation")
    failure_cases = models.JSONField(default=list, blank=True)
    failure_summary = models.JSONField(default=dict, blank=True)
    recommendation = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    celery_task_id = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["owner", "status", "created_at"]),
            models.Index(fields=["kb", "created_at"]),
        ]

    def __str__(self):
        return f"ExperimentPlan#{self.id}:{self.status}"


class RagExperimentVariant(models.Model):
    plan = models.ForeignKey(RagExperimentPlan, on_delete=models.CASCADE, related_name="variants")
    eval_run = models.ForeignKey(RagEvalRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="experiment_variants")
    name = models.CharField(max_length=120)
    hypothesis = models.TextField(blank=True, default="")
    rag_options = models.JSONField(default=dict, blank=True)
    result_summary = models.JSONField(default=dict, blank=True)
    is_winner = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} -> {self.eval_run_id or '-'}"


class RagEvalCaseResult(models.Model):
    run = models.ForeignKey(RagEvalRun, on_delete=models.CASCADE, related_name="case_results")
    case_id = models.CharField(max_length=120)
    case_type = models.CharField(max_length=40, blank=True, default="")
    suite = models.CharField(max_length=30, blank=True, default="")
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
    deterministic_results = models.JSONField(default=dict, blank=True)
    judge_results = models.JSONField(default=dict, blank=True)
    execution_metrics = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["id"]

class RagAgentAction(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("rejected", "Rejected"),
    ]
    ACTION_TYPE_CHOICES = [
        ("create_regression_case", "Create Regression Case"),
        ("run_experiment_plan", "Run Experiment Plan"),
        ("publish_rag_config", "Publish RAG Config"),
        ("rollback_rag_config", "Rollback RAG Config"),
    ]

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="rag_agent_actions")
    kb = models.ForeignKey(KnowledgeBase, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_agent_actions")
    trace = models.ForeignKey(RagTrace, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_agent_actions")
    eval_run = models.ForeignKey(RagEvalRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_agent_actions")
    eval_case_result = models.ForeignKey(RagEvalCaseResult, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_agent_actions")
    created_case = models.ForeignKey(RagBenchmarkCase, null=True, blank=True, on_delete=models.SET_NULL, related_name="agent_actions")
    action_uid = models.CharField(max_length=160)
    action_type = models.CharField(max_length=50, choices=ACTION_TYPE_CHOICES)
    source = models.CharField(max_length=50, blank=True, default="")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True, default="")
    confirm_label = models.CharField(max_length=60, blank=True, default="Confirm")
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    rejected_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "action_uid"], name="unique_agent_action_per_owner"),
        ]
        indexes = [
            models.Index(fields=["owner", "status", "created_at"]),
            models.Index(fields=["kb", "created_at"]),
            models.Index(fields=["trace", "created_at"]),
            models.Index(fields=["eval_run", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action_type}:{self.action_uid}"


class RagConfigVersion(models.Model):
    SOURCE_CHOICES = [("initial", "Initial"), ("manual", "Manual"), ("experiment", "Experiment"), ("rollback", "Rollback")]
    VALIDATION_CHOICES = [
        ("candidate", "Candidate"), ("release_running", "Release Running"),
        ("release_passed", "Release Passed"), ("release_failed", "Release Failed"),
    ]
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="config_versions")
    version = models.PositiveIntegerField()
    payload = models.JSONField(default=dict)
    signature = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="manual")
    validation_status = models.CharField(max_length=30, choices=VALIDATION_CHOICES, default="candidate")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children")
    experiment_plan = models.ForeignKey(RagExperimentPlan, null=True, blank=True, on_delete=models.SET_NULL, related_name="config_versions")
    winner_variant = models.ForeignKey(RagExperimentVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="config_versions")
    release_eval_run = models.ForeignKey(RagEvalRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="release_config_versions")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_config_versions")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["kb", "version"], name="unique_rag_config_version")]


class RagConfigDeployment(models.Model):
    OPERATION_CHOICES = [("publish", "Publish"), ("rollback", "Rollback")]
    kb = models.ForeignKey(KnowledgeBase, on_delete=models.CASCADE, related_name="config_deployments")
    previous_version = models.ForeignKey(RagConfigVersion, null=True, blank=True, on_delete=models.SET_NULL, related_name="deployments_from")
    target_version = models.ForeignKey(RagConfigVersion, on_delete=models.PROTECT, related_name="deployments_to")
    action = models.ForeignKey(RagAgentAction, null=True, blank=True, on_delete=models.SET_NULL, related_name="config_deployments")
    operation = models.CharField(max_length=20, choices=OPERATION_CHOICES)
    reason = models.TextField(blank=True, default="")
    deployed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="rag_config_deployments")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class DocumentParseBenchmarkCase(models.Model):
    SUITE_CHOICES = RagBenchmarkCase.SUITE_CHOICES
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="document_parse_cases")
    case_id = models.CharField(max_length=120)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="parse_eval_cases/%Y/%m/%d/")
    suite = models.CharField(max_length=30, choices=SUITE_CHOICES, default="benchmark")
    tags = models.JSONField(default=list, blank=True)
    expected_page_count = models.PositiveIntegerField(null=True, blank=True)
    expected_ocr_pages = models.JSONField(default=list, blank=True)
    expected_headings = models.JSONField(default=list, blank=True)
    expected_terms_by_page = models.JSONField(default=dict, blank=True)
    expected_block_types = models.JSONField(default=list, blank=True)
    expected_table_terms = models.JSONField(default=list, blank=True)
    thresholds = models.JSONField(default=dict, blank=True)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["case_id", "id"]
        constraints = [models.UniqueConstraint(fields=["owner", "case_id"], name="unique_parse_case_per_owner")]


class DocumentParseEvalRun(models.Model):
    STATUS_CHOICES = [("queued", "Queued"), ("running", "Running"), ("completed", "Completed"), ("failed", "Failed")]
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="document_parse_eval_runs")
    suite = models.CharField(max_length=30, choices=RagBenchmarkCase.SUITE_CHOICES, default="benchmark")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    celery_task_id = models.CharField(max_length=100, blank=True, default="")
    case_count = models.PositiveIntegerField(default=0)
    passed_count = models.PositiveIntegerField(default=0)
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class DocumentParseEvalCaseResult(models.Model):
    run = models.ForeignKey(DocumentParseEvalRun, on_delete=models.CASCADE, related_name="case_results")
    case = models.ForeignKey(DocumentParseBenchmarkCase, on_delete=models.PROTECT, related_name="eval_results")
    passed = models.BooleanField(default=False)
    metrics = models.JSONField(default=dict, blank=True)
    checks = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)
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

