from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from cagent_os.config import constants


@dataclass(frozen=True)
class Settings:
    app_name: str = "CagentOS"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    default_model_alias: str = "claude-balanced"
    proxy_enabled: bool = False
    proxy_url: str = ""
    socks_proxy: str = ""
    llm_provider: str = "openrouter"
    llm_api_key: str = ""
    llm_base_url: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_models_url: str = "https://openrouter.ai/api/v1/models"
    openrouter_http_referer: str = ""
    openrouter_app_name: str = "cagent-os"
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    model_aliases: dict[str, str] | None = None
    google_api_key: str = ""
    search_engine_id: str = ""
    tavily_api_key: str = ""
    jina_api_key: str = ""
    fred_api_key: str = ""
    market_http_base_url: str = ""
    market_http_token: str = ""
    fmp_base_url: str = ""
    conversation_db_path: str = "./data/conversations.db"
    memory_db_path: str = "./data/memory.db"
    trace_db_path: str = "./data/trace.db"
    mcp_servers_config: str = "./config/mcp_servers.json"
    default_principal_id: str = "default"
    default_user_id: str = "default"
    skills_data_dir: str = "./data/skills"
    shared_skills_dir: str = "./skills"

    @property
    def effective_proxy(self) -> str:
        if not self.proxy_enabled:
            return ""
        return self.proxy_url or self.socks_proxy

    @classmethod
    def from_env(cls) -> "Settings":
        proxy_url = str(constants.PROXY_URL or constants.SOCKS_PROXY).strip()
        return cls(
            app_name=constants.APP_NAME,
            api_host=constants.API_HOST,
            api_port=constants.API_PORT,
            debug=constants.DEBUG,
            default_model_alias=constants.DEFAULT_MODEL_ALIAS,
            proxy_enabled=constants.PROXY_ENABLED,
            proxy_url=proxy_url,
            socks_proxy=proxy_url,
            llm_provider=constants.LLM_PROVIDER,
            llm_api_key=constants.LLM_API_KEY,
            llm_base_url=constants.LLM_BASE_URL,
            openrouter_api_key=constants.OPENROUTER_API_KEY,
            openrouter_base_url=constants.OPENROUTER_BASE_URL,
            openrouter_models_url=constants.OPENROUTER_MODELS_URL,
            openrouter_http_referer=constants.OPENROUTER_HTTP_REFERER,
            openrouter_app_name=constants.OPENROUTER_APP_NAME,
            deepseek_api_key=constants.DEEPSEEK_API_KEY,
            openai_api_key=constants.OPENAI_API_KEY,
            anthropic_api_key=constants.ANTHROPIC_API_KEY,
            model_aliases=dict(constants.MODEL_ALIASES),
            google_api_key=constants.GOOGLE_API_KEY,
            search_engine_id=constants.SEARCH_ENGINE_ID,
            tavily_api_key=constants.TAVILY_API_KEY,
            jina_api_key=constants.JINA_API_KEY,
            fred_api_key=constants.FRED_API_KEY,
            market_http_base_url=constants.MARKET_HTTP_BASE_URL,
            market_http_token=constants.MARKET_HTTP_TOKEN,
            fmp_base_url=constants.FMP_BASE_URL,
            conversation_db_path=constants.CONVERSATION_DB_PATH,
            memory_db_path=constants.MEMORY_DB_PATH,
            trace_db_path=constants.TRACE_DB_PATH,
            mcp_servers_config=constants.MCP_SERVERS_CONFIG,
            default_principal_id=constants.DEFAULT_PRINCIPAL_ID,
            default_user_id=constants.DEFAULT_USER_ID,
            skills_data_dir=constants.SKILLS_DATA_DIR,
            shared_skills_dir=constants.SHARED_SKILLS_DIR,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
