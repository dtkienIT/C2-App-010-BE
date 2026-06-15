from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    supabase_project_ref: str = ""
    supabase_url: str = ""
    supabase_db_url: str = ""
    supabase_service_role_key: str = ""
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    newsfeed_allowed_hosts: str = "feeds.bbci.co.uk,feeds.npr.org"
    newsfeed_cache_max_items: int = 24
    newsfeed_cache_ttl_minutes: int = 20
    newsfeed_request_timeout_seconds: int = 8
    postgres_pool_max_size: int = 8

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def newsfeed_allowed_hosts_list(self) -> list[str]:
        return [host.strip().lower() for host in self.newsfeed_allowed_hosts.split(",") if host.strip()]

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def postgres_enabled(self) -> bool:
        return bool(self.supabase_db_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
