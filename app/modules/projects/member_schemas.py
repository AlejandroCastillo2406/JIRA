from uuid import UUID

from pydantic import BaseModel, EmailStr, model_validator


class ProjectMemberAdd(BaseModel):
    """Permite el flujo nuevo por user_id y conserva compatibilidad por correo."""

    user_id: UUID | None = None
    email: EmailStr | None = None
    role_code: str = "DEVELOPER"

    @model_validator(mode="after")
    def require_user_reference(self):
        if not self.user_id and not self.email:
            raise ValueError("Debes indicar user_id o email")
        return self


class ProjectMemberUpdate(BaseModel):
    role_code: str
