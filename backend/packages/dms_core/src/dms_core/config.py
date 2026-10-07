from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str = ""
    fake_ai: bool = False
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    embed_model: str = "baai/bge-m3"
    embed_dim: int = 1024
    llm_fast_model: str = "google/gemini-3.5-flash-lite"
    llm_answer_model: str = "anthropic/claude-haiku-4.5"
    vision_ocr_model: str = "qwen/qwen3-vl-32b-instruct"
    agent_model: str = "anthropic/claude-haiku-4.5"
    agent_max_tool_calls: int = 8
    agent_max_history_turns: int = 6

    database_url: str = "postgresql://dms:dms@localhost:5432/dms"
    opensearch_url: str = "http://localhost:9200"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "documents"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 720
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    cors_origin_regex: str = ""

    ocr_text_threshold: int = 50
    ocr_render_dpi: int = 200
    chunk_target_tokens: int = 450
    chunk_max_tokens: int = 500
    chunk_overlap_ratio: float = 0.12
    embed_batch_size: int = 32
    minhash_perm: int = 128
    minhash_bands: int = 32
    near_dup_jaccard: float = 0.8
    semantic_dup_threshold: float = 0.95
    tag_similarity_threshold: float = 0.55
    title_llm_threshold: float = 0.6
    raptor_small_doc_chunks: int = 8
    raptor_max_depth: int = 3
    rrf_k: int = 60
    knn_k: int = 50
    superseded_penalty: float = 0.7
    ask_top_k: int = 8
    job_max_attempts: int = 3
    worker_poll_seconds: float = 1.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
