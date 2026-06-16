from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
ROOT_ENV_FILE = ROOT_DIR / ".env"


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
    environment: str = "development"
    vite_enable_web_push: bool = True
    vite_enable_notification_test: bool = False
    vite_web_push_public_key: str = ""
    web_push_enabled: bool = False
    web_push_vapid_public_key: str = ""
    web_push_vapid_private_key: str = ""
    web_push_vapid_subject: str = "mailto:team@example.com"
    notification_worker_poll_seconds: int = 10
    notification_worker_batch_size: int = 50
    notification_worker_embedded_enabled: bool = True
    notification_max_attempts: int = 5
    notification_max_lateness_seconds: int = 1800
    web_push_ttl_seconds: int = 3600
    notification_test_cooldown_seconds: int = 60
    enable_notification_test_endpoint: bool = False
    max_study_reminders_per_user: int = 12
    email_notifications_enabled: bool = False
    frontend_base_url: str = "http://localhost:5173"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "Study Buddy"
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 10

    model_config = SettingsConfigDict(env_file=str(ROOT_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

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
