from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserView(BaseModel):
    id: str
    email: str
    display_name: str
    timezone: str
    locale: str
    global_role: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserView
