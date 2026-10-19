from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ProjectFlow API"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    secret_key: str
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    database_url: str
    db_schema: str = "public"
    cors_origins: str = "http://localhost:3000"
    cookie_secure: bool = False
    frontend_url: str = "http://localhost:3000"

    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "Admin123!"
    bootstrap_admin_name: str = "Administrador"

    # AWS SDK: boto3 también soporta IAM Roles/Profiles. Estas variables permiten
    # configuración explícita cuando se ejecuta fuera de AWS.
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None

    # S3 privado para imágenes de tickets.
    s3_bucket: str | None = None
    s3_presign_expiry_seconds: int = 900
    s3_max_image_bytes: int = 10 * 1024 * 1024

    # SES directo: se activa al configurar un remitente.
    ses_from_email: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
