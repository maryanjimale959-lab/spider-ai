"""Authentication and user management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import User
from app.schemas import LoginRequest, RegisterRequest, TokenOut, UserOut
from app.security import CurrentUser, create_access_token, get_current_user, hash_password, require_roles, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already uses this email")
    user = User(
        email=payload.email.lower(), full_name=payload.full_name.strip(), role=payload.role,
        password_hash=hash_password(payload.password), institution=payload.institution,
    )
    db.add(user)
    db.commit()
    token, expires_at = create_access_token(user)
    return TokenOut(access_token=token, expires_at=expires_at, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        # Same message for both cases: do not leak which emails have accounts.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")
    token, expires_at = create_access_token(user)
    return TokenOut(access_token=token, expires_at=expires_at, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return db.scalars(select(User).order_by(User.full_name)).all()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
):
    """Administrators can create teacher/student accounts and grant access on a user's behalf."""
    if db.scalar(select(User).where(User.email == payload.email.lower())) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already uses this email")
    user = User(
        email=payload.email.lower(), full_name=payload.full_name.strip(), role=payload.role,
        password_hash=hash_password(payload.password), institution=payload.institution,
    )
    db.add(user)
    db.commit()
    return user


@router.patch("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate(
    user_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(require_roles("admin")),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    user.is_active = False
    db.commit()
    return user
