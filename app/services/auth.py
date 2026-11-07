from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import (
    generate_token,
    hash_password,
    token_expiry,
    verify_password,
)
from app.models.enums import UserRole
from app.models.user import ApiToken, User


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or len(normalized) < 5:
        raise ValueError("a valid email is required")
    return normalized


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def get_user(self, user_id: int) -> User | None:
        return self.db.get(User, user_id)

    def get_user_by_email(self, email: str) -> User | None:
        normalized = _normalize_email(email)
        return self.db.scalar(
            select(User).where(func.lower(User.email) == normalized)
        )

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.get_user_by_email(email)
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    def create_user(
        self,
        email: str,
        password: str,
        tenant_id: int,
        role: UserRole = UserRole.VIEWER,
        is_active: bool = True,
        is_superadmin: bool = False,
    ) -> User:
        user = User(
            email=_normalize_email(email),
            tenant_id=tenant_id,
            password_hash=hash_password(password),
            role=role,
            is_active=is_active,
            is_superadmin=is_superadmin,
        )
        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            return user
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError("email already exists") from exc
        except Exception:
            self.db.rollback()
            raise

    def update_user(
        self,
        user_id: int,
        *,
        role: UserRole | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> User | None:
        user = self.get_user(user_id)
        if user is None:
            return None
        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active
        if password is not None:
            user.password_hash = hash_password(password)
        try:
            self.db.commit()
            self.db.refresh(user)
            return user
        except Exception:
            self.db.rollback()
            raise

    def count_users(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(User)) or 0)

    def list_users(self, tenant_id: int | None = None) -> list[User]:
        statement = select(User).order_by(User.id)
        if tenant_id is not None:
            statement = statement.where(User.tenant_id == tenant_id)
        return list(self.db.scalars(statement).all())

    def issue_token(
        self,
        user: User,
        *,
        name: str = "default",
        expires_hours: int | None = None,
    ) -> tuple[str, ApiToken, datetime]:
        raw, token_hash = generate_token()
        expires_at = token_expiry(expires_hours)
        token = ApiToken(
            user_id=user.id,
            name=(name.strip() or "default")[:100],
            token_hash=token_hash,
            expires_at=expires_at,
        )
        try:
            self.db.add(token)
            self.db.commit()
            self.db.refresh(token)
            return raw, token, expires_at
        except Exception:
            self.db.rollback()
            raise

    def list_tokens(self, user_id: int) -> list[ApiToken]:
        return list(
            self.db.scalars(
                select(ApiToken)
                .where(ApiToken.user_id == user_id)
                .order_by(ApiToken.id.desc())
            ).all()
        )

    def revoke_token(
        self,
        token_id: int,
        *,
        user_id: int | None = None,
        tenant_id: int | None = None,
        is_admin: bool = False,
        is_superadmin: bool = False,
    ) -> bool:
        token = self.db.get(ApiToken, token_id)
        if token is None:
            return False
        if not is_superadmin:
            if is_admin:
                if tenant_id is None or token.user is None:
                    return False
                if token.user.tenant_id != tenant_id:
                    return False
            elif user_id is None or token.user_id != user_id:
                return False
        self.db.delete(token)
        self.db.commit()
        return True
