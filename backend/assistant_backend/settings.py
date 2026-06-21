import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str]) -> list[str]:
    value = os.getenv(name)
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


def env_json(name: str, default):
    value = os.getenv(name)
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-aiassistant-dev")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["127.0.0.1", "localhost"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "rag",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "assistant_backend.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "assistant_backend.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "db.sqlite3")),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:5174"])
CORS_ALLOW_CREDENTIALS = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen-plus")
API_KEY = os.getenv("API_KEY") or os.getenv("DASHSCOPE_API_KEY")
API_BASE = os.getenv("API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "1024"))
EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
QUERY_REWRITE_STRATEGY = os.getenv("QUERY_REWRITE_STRATEGY", "rule")
CONVERSATION_CONTEXT_TURNS = int(os.getenv("CONVERSATION_CONTEXT_TURNS", "6"))
SESSION_SUMMARY_ENABLED = env_bool("SESSION_SUMMARY_ENABLED", True)
SESSION_SUMMARY_TRIGGER_MESSAGES = int(os.getenv("SESSION_SUMMARY_TRIGGER_MESSAGES", "12"))
SESSION_SUMMARY_MAX_CHARS = int(os.getenv("SESSION_SUMMARY_MAX_CHARS", "2000"))
SESSION_SUMMARY_NEW_MESSAGES_LIMIT = int(os.getenv("SESSION_SUMMARY_NEW_MESSAGES_LIMIT", "40"))
SESSION_SUMMARY_MODEL = os.getenv("SESSION_SUMMARY_MODEL", "")
SESSION_SUMMARY_MAX_OUTPUT_TOKENS = int(os.getenv("SESSION_SUMMARY_MAX_OUTPUT_TOKENS", "1024"))
BM25_TOP_K = int(os.getenv("BM25_TOP_K", "5"))
BM25_K1 = float(os.getenv("BM25_K1", "1.5"))
BM25_B = float(os.getenv("BM25_B", "0.75"))
HYBRID_TOP_K = int(os.getenv("HYBRID_TOP_K", str(RAG_TOP_K)))
RRF_K = int(os.getenv("RRF_K", "60"))
RERANK_ENABLED = env_bool("RERANK_ENABLED", True)
RERANK_MODEL = os.getenv("RERANK_MODEL", "qwen3-rerank")
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", str(RAG_TOP_K)))
RERANK_CANDIDATE_N = int(os.getenv("RERANK_CANDIDATE_N", str(HYBRID_TOP_K)))
RERANK_API_URL = os.getenv(
    "RERANK_API_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
)
RERANK_TIMEOUT = float(os.getenv("RERANK_TIMEOUT", "10"))
CONTEXT_COMPRESSION_ENABLED = env_bool("CONTEXT_COMPRESSION_ENABLED", True)
CONTEXT_COMPRESSION_STRATEGY = os.getenv("CONTEXT_COMPRESSION_STRATEGY", "structure_aware")
COMPRESSION_MAX_SENTENCES_PER_CHUNK = int(os.getenv("COMPRESSION_MAX_SENTENCES_PER_CHUNK", "8"))
COMPRESSION_SENTENCE_WINDOW = int(os.getenv("COMPRESSION_SENTENCE_WINDOW", "3"))
COMPRESSION_LIST_ITEM_WINDOW = int(os.getenv("COMPRESSION_LIST_ITEM_WINDOW", "8"))
COMPRESSION_MIN_SCORE = float(os.getenv("COMPRESSION_MIN_SCORE", "0.05"))
LLM_COMPRESSION_API_KEY = os.getenv("LLM_COMPRESSION_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
LLM_COMPRESSION_API_BASE = os.getenv("LLM_COMPRESSION_API_BASE", os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com"))
LLM_COMPRESSION_MODEL = os.getenv("LLM_COMPRESSION_MODEL", "deepseek-v4-flash")
LLM_COMPRESSION_TIMEOUT = float(os.getenv("LLM_COMPRESSION_TIMEOUT", "20"))
LLM_COMPRESSION_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_COMPRESSION_MAX_OUTPUT_TOKENS", "512"))
VECTOR_STORE = os.getenv("VECTOR_STORE", "milvus_lite")
MILVUS_URI = os.getenv("MILVUS_URI", str(BASE_DIR / "vector_store" / "milvus_lite.db"))
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "aiassistant_chunks")
LANGGRAPH_CHECKPOINT_DB = os.getenv("LANGGRAPH_CHECKPOINT_DB", str(BASE_DIR / "agent_state" / "langgraph_checkpoints.sqlite3"))
MODEL_TOKEN_PRICES = env_json("MODEL_TOKEN_PRICES", {})
MODEL_SLOW_REQUEST_MS = int(os.getenv("MODEL_SLOW_REQUEST_MS", "3000"))
CHAT_STREAM_INCLUDE_USAGE = env_bool("CHAT_STREAM_INCLUDE_USAGE", False)
RAG_STREAM_MAX_ACTIVE_PER_PROCESS = int(os.getenv("RAG_STREAM_MAX_ACTIVE_PER_PROCESS", "32"))
RAG_STREAM_RESPONSE_TIMEOUT_SECONDS = int(os.getenv("RAG_STREAM_RESPONSE_TIMEOUT_SECONDS", "3600"))
EVAL_RUN_STALE_TIMEOUT_SECONDS = int(os.getenv("EVAL_RUN_STALE_TIMEOUT_SECONDS", "3600"))

DOCUMENT_MAX_UPLOAD_BYTES = int(os.getenv("DOCUMENT_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
DOCUMENT_MAX_PDF_PAGES = int(os.getenv("DOCUMENT_MAX_PDF_PAGES", "300"))
DOCUMENT_MAX_DOCX_UNCOMPRESSED_BYTES = int(os.getenv("DOCUMENT_MAX_DOCX_UNCOMPRESSED_BYTES", str(200 * 1024 * 1024)))
DOCUMENT_MAX_ZIP_RATIO = float(os.getenv("DOCUMENT_MAX_ZIP_RATIO", "100"))
DOCUMENT_MAX_DOCX_FILES = int(os.getenv("DOCUMENT_MAX_DOCX_FILES", "10000"))
DOCUMENT_NONBLANK_PAGE_MIN_CHARS = int(os.getenv("DOCUMENT_NONBLANK_PAGE_MIN_CHARS", "20"))
PDF_NATIVE_TEXT_MIN_CHARS = int(os.getenv("PDF_NATIVE_TEXT_MIN_CHARS", "40"))
PDF_NATIVE_GARBLED_RATE = float(os.getenv("PDF_NATIVE_GARBLED_RATE", "0.05"))
DOCUMENT_REVIEW_MIN_COVERAGE = float(os.getenv("DOCUMENT_REVIEW_MIN_COVERAGE", "0.90"))
DOCUMENT_REVIEW_MAX_BLANK_RATE = float(os.getenv("DOCUMENT_REVIEW_MAX_BLANK_RATE", "0.10"))
DOCUMENT_REVIEW_MAX_GARBLED_RATE = float(os.getenv("DOCUMENT_REVIEW_MAX_GARBLED_RATE", "0.02"))
PADDLEOCR_JOB_URL = os.getenv("PADDLEOCR_JOB_URL", "")
PADDLEOCR_TOKEN = os.getenv("PADDLEOCR_TOKEN", "")
PADDLEOCR_MODEL = os.getenv("PADDLEOCR_MODEL", "PaddleOCR-VL-1.6")
PADDLEOCR_POLL_INTERVAL_SECONDS = float(os.getenv("PADDLEOCR_POLL_INTERVAL_SECONDS", "5"))
PADDLEOCR_JOB_TIMEOUT_SECONDS = int(os.getenv("PADDLEOCR_JOB_TIMEOUT_SECONDS", "1200"))
PADDLEOCR_CONNECT_TIMEOUT = float(os.getenv("PADDLEOCR_CONNECT_TIMEOUT", "10"))
PADDLEOCR_READ_TIMEOUT = float(os.getenv("PADDLEOCR_READ_TIMEOUT", "60"))
PADDLEOCR_HTTP_RETRIES = int(os.getenv("PADDLEOCR_HTTP_RETRIES", "3"))
PADDLEOCR_MAX_RESULT_BYTES = int(os.getenv("PADDLEOCR_MAX_RESULT_BYTES", str(100 * 1024 * 1024)))

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = int(os.getenv("CELERY_TASK_TIME_LIMIT", "1800"))
CELERY_TASK_SOFT_TIME_LIMIT = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "1740"))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_PUBLISH_RETRY = False
CELERY_BROKER_TRANSPORT_OPTIONS = {"socket_connect_timeout": 2, "socket_timeout": 5}
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True

class ExactLevelFilter(logging.Filter):
    def __init__(self, level_name):
        super().__init__()
        self.levelno = logging._nameToLevel[level_name]

    def filter(self, record):
        return record.levelno == self.levelno


LOG_DATE_DIR = BASE_DIR / "logs" / datetime.now().strftime("%Y-%m-%d")
LOG_DATE_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "debug_only": {"()": "assistant_backend.settings.ExactLevelFilter", "level_name": "DEBUG"},
        "info_only": {"()": "assistant_backend.settings.ExactLevelFilter", "level_name": "INFO"},
        "warning_only": {"()": "assistant_backend.settings.ExactLevelFilter", "level_name": "WARNING"},
        "error_only": {"()": "assistant_backend.settings.ExactLevelFilter", "level_name": "ERROR"},
    },
    "formatters": {
        "default": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        },
        "all_file": {
            "class": "logging.FileHandler",
            "filename": str(LOG_DATE_DIR / "all.log"),
            "encoding": "utf-8",
            "formatter": "default",
        },
        "debug_file": {
            "class": "logging.FileHandler",
            "filename": str(LOG_DATE_DIR / "debug.log"),
            "encoding": "utf-8",
            "formatter": "default",
            "filters": ["debug_only"],
        },
        "info_file": {
            "class": "logging.FileHandler",
            "filename": str(LOG_DATE_DIR / "info.log"),
            "encoding": "utf-8",
            "formatter": "default",
            "filters": ["info_only"],
        },
        "warning_file": {
            "class": "logging.FileHandler",
            "filename": str(LOG_DATE_DIR / "warning.log"),
            "encoding": "utf-8",
            "formatter": "default",
            "filters": ["warning_only"],
        },
        "error_file": {
            "class": "logging.FileHandler",
            "filename": str(LOG_DATE_DIR / "error.log"),
            "encoding": "utf-8",
            "formatter": "default",
            "filters": ["error_only"],
        },
    },
    "root": {
        "handlers": ["console", "all_file", "debug_file", "info_file", "warning_file", "error_file"],
        "level": "INFO",
    },
}
