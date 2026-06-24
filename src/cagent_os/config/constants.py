"""Application constants — all secrets come from environment variables."""

import os
from enum import Enum

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class AnswerMode(str, Enum):
    MINIMAL = "minimal"
    STANDARD = "standard"
    DEEP = "deep"

    @classmethod
    def from_str(cls, value: str | None) -> "AnswerMode | None":
        if value is None:
            return None
        try:
            return cls(value)
        except ValueError:
            return None


APP_NAME = os.getenv("APP_NAME", "CagentOS")
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

DEFAULT_MODEL_ALIAS = os.getenv("DEFAULT_MODEL_ALIAS", "claude-balanced")
PROXY_ENABLED = bool(os.getenv("HTTP_PROXY", "") or os.getenv("HTTPS_PROXY", ""))
PROXY_URL = os.getenv("HTTP_PROXY", "")
SOCKS_PROXY = os.getenv("SOCKS_PROXY", "")

# ── LLM Provider selection ──
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openrouter")  # openrouter | deepseek | openai | anthropic | custom
LLM_API_KEY = os.getenv("LLM_API_KEY", "")              # generic key (fallback when provider-specific key not set)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")            # custom endpoint (required when LLM_PROVIDER=custom)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODELS_URL = os.getenv("OPENROUTER_MODELS_URL", "https://openrouter.ai/api/v1/models")
OPENROUTER_HTTP_REFERER = os.getenv("OPENROUTER_HTTP_REFERER", "")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "cagent-os")

# ── API Keys (env vars only — no hardcoded secrets) ──
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID", "")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
JINA_API_KEY = os.getenv("JINA_API_KEY", "")

PROVIDER_GOOGLE = "google"
PROVIDER_PERPLEXITY = "perplexity"
PROVIDER_TAVILY = "tavily"
SELECTED_SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", PROVIDER_GOOGLE)
MAIN_SEARCH_SOURCE_NAMES = [PROVIDER_GOOGLE, PROVIDER_PERPLEXITY, PROVIDER_TAVILY]

PROVIDER_OPENAI = "openai"
PROVIDER_FASTEMBED = "fastembed"
SELECTED_EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", PROVIDER_OPENAI)

FASTEMBED_MODELS = {
    "BGE_SMALL": "BAAI/bge-small-en-v1.5",
    "BGE_BASE": "BAAI/bge-base-en-v1.5",
    "ALL_MINILM": "sentence-transformers/all-MiniLM-L6-v2",
    "NOMIC_EMBED": "nomic-ai/nomic-embed-text-v1.5",
}
SELECTED_FASTEMBED_MODEL = os.getenv("FASTEMBED_MODEL", FASTEMBED_MODELS["BGE_SMALL"])

MARKET_HTTP_BASE_URL = os.getenv("MARKET_HTTP_BASE_URL", "")
MARKET_HTTP_TOKEN = os.getenv("MARKET_HTTP_TOKEN", "")
FMP_BASE_URL = os.getenv("FMP_BASE_URL", "")

# ── Model aliases (task → model mapping) ──
_MODEL_ALIASES_ENV = os.getenv("MODEL_ALIASES", "")
if _MODEL_ALIASES_ENV:
    import json
    MODEL_ALIASES: dict[str, str] = json.loads(_MODEL_ALIASES_ENV)
else:
    MODEL_ALIASES = {
        "claude-balanced": "anthropic/claude-sonnet-4.6",
        "opus-strong": "anthropic/claude-opus-4.6",
        "gpt-fast": "openai/gpt-5-mini",
        "gpt-strong": "openai/gpt-5.4",
        "gemini-strong": "google/gemini-3.1-pro-preview",
        "gemini-cheap": "google/gemini-2.5-flash-lite",
        "gemini-balanced": "google/gemini-2.5-flash",
    }

GPT_BASE_URL = f"{OPENROUTER_BASE_URL}/chat/completions"
GPT_MODEL = os.getenv("GPT_MODEL", "openai/gpt-5.4")
GPT_MODEL_FAST = os.getenv("GPT_MODEL_FAST", "openai/gpt-4o")
GPT_REASONING_EFFORT = os.getenv("GPT_REASONING_EFFORT", "high")

# ── SQLite paths ──
SQLITE_DATA_DIR = os.getenv("SQLITE_DATA_DIR", "./data")
CONVERSATION_DB_PATH = os.getenv("CONVERSATION_DB_PATH", f"{SQLITE_DATA_DIR}/conversations.db")
MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", f"{SQLITE_DATA_DIR}/memory.db")
TRACE_DB_PATH = os.getenv("TRACE_DB_PATH", f"{SQLITE_DATA_DIR}/trace.db")

MCP_SERVERS_CONFIG = os.getenv("MCP_SERVERS_CONFIG", "./config/mcp_servers.json")

DEFAULT_PRINCIPAL_ID = os.getenv("DEFAULT_PRINCIPAL_ID", "default")
DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "default")
SKILLS_DATA_DIR = os.getenv("SKILLS_DATA_DIR", "./data/skills")
SHARED_SKILLS_DIR = os.getenv("SHARED_SKILLS_DIR", "./skills")
