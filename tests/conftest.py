import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-only")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
