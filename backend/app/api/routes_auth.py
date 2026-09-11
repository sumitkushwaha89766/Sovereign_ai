"""Auth routes (Architecture.md §5 contract, §6 workflow)."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import authenticate_user, create_access_token
from app.core.audit import record_audit
from app.db.database import get_db
from app.models.schemas import LoginRequest, LoginResponse

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = authenticate_user(db, payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(subject=user.username, role=user.role)
    record_audit(db, "login_success", f"User {user.username} signed in", user_id=user.id)
    return LoginResponse(access_token=token, role=user.role)
