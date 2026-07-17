from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.dependencies import get_current_active_user, get_current_admin_user
from src.auth.schemas import (
    MessageResponse,
    RefreshTokenRequest,
    TokenRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from src.auth.models import User
from src.auth.service import AuthService
from src.common.database import get_db
from src.common.rate_limit import rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])

# Brute-force mitigation: 5 attempts / 5 minutes / IP. Login is the higher-value
# target so it gets the tighter budget; register is limited mainly to stop
# automated account-creation spam.
_login_rate_limit = rate_limiter(times=5, seconds=300, scope="login")
_register_rate_limit = rate_limiter(times=10, seconds=300, scope="register")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_register_rate_limit)],
)
async def register(user_data: UserCreate, session: AsyncSession = Depends(get_db)):
    service = AuthService(session)
    return await service.register(user_data)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(_login_rate_limit)])
async def login(credentials: TokenRequest, session: AsyncSession = Depends(get_db)):
    service = AuthService(session)
    return await service.login(credentials.email, credentials.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: RefreshTokenRequest, session: AsyncSession = Depends(get_db)):
    service = AuthService(session)
    return await service.refresh(request.refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    return UserResponse.model_validate(current_user)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: RefreshTokenRequest, session: AsyncSession = Depends(get_db)):
    service = AuthService(session)
    await service.logout(request.refresh_token)
    return MessageResponse(message="Logged out successfully")


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(
    current_user: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_db)
):
    service = AuthService(session)
    await service.logout_all(current_user.id)
    return MessageResponse(message="Logged out from all devices")


@router.get("/admin/users", response_model=list[UserResponse])
async def list_users(
    current_user: User = Depends(get_current_admin_user),
    session: AsyncSession = Depends(get_db),
):
    from src.auth.repository import UserRepository

    repo = UserRepository(session)
    users = await repo.get_all()
    return [UserResponse.model_validate(u) for u in users]