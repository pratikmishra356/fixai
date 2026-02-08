"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/fixai",
        alias="DATABASE_URL",
    )

    # Service URLs (defaults, can be overridden per-org)
    code_parser_base_url: str = Field(
        default="http://localhost:8000",
        alias="CODE_PARSER_BASE_URL",
    )
    metrics_explorer_base_url: str = Field(
        default="http://localhost:8002",
        alias="METRICS_EXPLORER_BASE_URL",
    )
    logs_explorer_base_url: str = Field(
        default="http://localhost:8003",
        alias="LOGS_EXPLORER_BASE_URL",
    )

    # Claude / LLM
    claude_bedrock_url: str = Field(
        default="https://llm-proxy.build.eng.toasttab.com",
        alias="CLAUDE_BEDROCK_URL",
    )
    claude_model_id: str = Field(
        default="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        alias="CLAUDE_MODEL_ID",
    )
    claude_api_key_helper_path: str = Field(
        default="/opt/homebrew/bin/toastApiKeyHelper",
        alias="CLAUDE_API_KEY_HELPER_PATH",
    )
    claude_api_key: str = Field(
        default="",
        alias="CLAUDE_API_KEY",
    )
    claude_max_tokens: int = Field(
        default=4096,
        alias="CLAUDE_MAX_TOKENS",
    )

    # Agent Guardrails
    agent_max_ai_calls: int = Field(
        default=15,
        alias="AGENT_MAX_AI_CALLS",
        description="Maximum LLM invocations per conversation turn",
    )
    agent_max_input_tokens: int = Field(
        default=80_000,
        alias="AGENT_MAX_INPUT_TOKENS",
        description="Estimated token budget for AI input context",
    )
    agent_recursion_limit: int = Field(
        default=35,
        alias="AGENT_RECURSION_LIMIT",
        description="Maximum graph steps (safety net, guardrails enforce actual limits)",
    )
    agent_tool_response_max_chars: int = Field(
        default=12_000,
        alias="AGENT_TOOL_RESPONSE_MAX_CHARS",
        description="Maximum characters in tool response before truncation",
    )
    agent_token_estimation_divisor: int = Field(
        default=4,
        alias="AGENT_TOKEN_ESTIMATION_DIVISOR",
        description="Divisor for token estimation (chars / divisor = tokens)",
    )

    # App
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    app_port: int = Field(default=8100, alias="APP_PORT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }


settings = Settings()
