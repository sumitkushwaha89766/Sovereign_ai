"""Authentication and authorization primitives (Architecture.md §6).

- Passwords are hashed with the local bcrypt library.
- Access tokens are short-lived JWTs (python-jose, HS256) signed with the local
  ``JWT_SECRET``. Nothing here contacts a non-localhost service.
- RBAC roles are ``engineer`` / ``approver`` / ``admin``, enforced per endpoint via
  ``require_roles`` (``admin`` is always permitted, per §6 "all of the above").

Demo users are seeded locally so ``/auth/login`` is testable in the MVP; all data
stays on the machine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.models.db_models import User

_bearer = HTTPBearer(auto_error=True)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

# Local-only demo accounts (one per role); same password for simplicity in the MVP.
DEMO_USERS = [
    ("engineer1", "demo1234", "engineer"),
    ("approver1", "demo1234", "approver"),
    ("admin1", "demo1234", "admin"),
]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    creds_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise creds_exc
    except JWTError:
        raise creds_exc
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        raise creds_exc
    return user


def require_roles(*roles: str):
    """Dependency factory allowing only the given roles (``admin`` is always allowed)."""
    allowed = set(roles) | {"admin"}

    def _dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role in {sorted(allowed)}",
            )
        return user

    return _dep


def seed_demo_users(db: Session) -> None:
    """Idempotently create the demo users (local MVP) if the users table is empty."""
    if db.execute(select(User)).first() is not None:
        return
    for username, password, role in DEMO_USERS:
        db.add(User(username=username, password_hash=hash_password(password), role=role))
    db.commit()
