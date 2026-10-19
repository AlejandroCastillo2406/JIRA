import re
from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    key: str = Field(min_length=2, max_length=10)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        value = value.upper().strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}", value):
            raise ValueError("La clave debe iniciar con letra y usar solo A-Z y 0-9")
        return value


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=5000)
