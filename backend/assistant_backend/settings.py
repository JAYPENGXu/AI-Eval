import json
import os
from datetime import timedelta
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
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
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
MODEL_TOKEN_PRICES = env_json("MODEL_TOKEN_PRICES", {})
MODEL_SLOW_REQUEST_MS = int(os.getenv("MODEL_SLOW_REQUEST_MS", "3000"))
CHAT_STREAM_INCLUDE_USAGE = env_bool("CHAT_STREAM_INCLUDE_USAGE", False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
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
        }
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
