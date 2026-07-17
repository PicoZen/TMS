from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib

from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.repository import RefreshTokenRepository, UserRepository
from src.auth.schemas import TokenResponse, UserCreate, UserResponse
from src.common.config import settings
from src.common.exceptions import ConflictException, UnauthorizedException
from src.common.models import User
from src.common.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)


def hash_token(token: str) -> str:
    """Hash a token using SHA256 for storage/lookup"""
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.user_repo = UserRepository(session)
        self.token_repo = RefreshTokenRepository(session)

    async def register(self, user_data: UserCreate) -> UserResponse:
        existing = await self.user_repo.get_by_email(user_data.email)
        if existing:
            raise ConflictException("Email already registered")

        user = await self.user_repo.create(user_data.email, user_data.password, user_data.role)
        return UserResponse.model_validate(user)

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.user_repo.get_by_email(email)
        if not user or not verify_password(password, user.password_hash):
            raise UnauthorizedException("Invalid credentials")

        return await self._create_tokens(user)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        hashed_token = hash_token(refresh_token)
        token = await self.token_repo.get_by_token(hashed_token)
        if not token or token.revoked or token.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
            raise UnauthorizedException("Invalid or expired refresh token")

        user = await self.user_repo.get_by_id(token.user_id)
        if not user:
            raise UnauthorizedException("User not found")

        await self.token_repo.revoke(token)
        return await self._create_tokens(user)

    async def logout(self, refresh_token: str) -> None:
        hashed_token = hash_token(refresh_token)
        token = await self.token_repo.get_by_token(hashed_token)
        if token:
            await self.token_repo.revoke(token)

    async def logout_all(self, user_id: int) -> None:
        await self.token_repo.revoke_all_user_tokens(user_id)

    async def _create_tokens(self, user: User) -> TokenResponse:
        access_token = create_access_token(str(user.id), user.email, user.role.value)
        refresh_token = create_refresh_token(str(user.id), user.email, user.role.value)

        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
        await self.token_repo.create(user.id, hash_token(refresh_token), expires_at)

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)