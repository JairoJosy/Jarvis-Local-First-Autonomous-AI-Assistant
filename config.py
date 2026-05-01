from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JARVIS_", extra="ignore")

    data_dir: Path = Field(
        default=Path("data"),
        description="Directory for SQLite, FAISS index, and logs.",
    )
    sqlite_path: Path = Field(
        default=Path("data/jarvis.db"),
        description="Structured memory and timeline database path.",
    )
    faiss_index_path: Path = Field(default=Path("data/vectors.faiss"))
    faiss_ids_path: Path = Field(default=Path("data/vector_ids.json"))

    timezone: str = "Asia/Kolkata"
    short_term_max_turns: int = 20
    semantic_top_k: int = 5
    memory_recent_limit: int = 15

    planner_temperature: float = 0.1
    chat_temperature: float = 0.4
    extractor_temperature: float = 0.0

    groq_api_key: str | None = None
    groq_model: str = "llama-3.1-8b-instant"
    groq_base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    ollama_base_url: str = "http://localhost:11434/api/chat"
    ollama_model: str = "llama3.1:8b"
    llm_timeout_seconds: float = 20.0

    vector_dim: int = 384
    embedding_provider: str = "hash"
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"

    local_ui_token: str = "local-dev-token"
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 300

    vosk_model_path: Path | None = None
    whisper_cli_path: str = "whisper"
    tesseract_cmd: str = "tesseract"
    adb_path: str = "adb"
    ffmpeg_path: str = "ffmpeg"
    lighthouse_cmd: str = "lighthouse"
    plugin_signing_secret: str | None = None

    def ensure_paths(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.faiss_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.faiss_ids_path.parent.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_paths()
    return settings
