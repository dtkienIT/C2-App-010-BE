from pydantic import BaseModel, Field, field_validator


class AuthRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("Invalid email")
        return value


class VerifyEmailRequest(BaseModel):
    verification_session_id: str
    otp: str = Field(min_length=6, max_length=6)

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        if not value.isdigit():
            raise ValueError("OTP must contain exactly 6 digits")
        return value


class ResendVerificationOtpRequest(BaseModel):
    verification_session_id: str


class AuthUser(BaseModel):
    id: str
    email: str
    displayName: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser
