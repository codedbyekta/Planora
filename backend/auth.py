"""
auth.py
-------
Handles everything related to authentication:

1. Password hashing/verification (using bcrypt via passlib).
2. Creating JWT access tokens on login.
3. Decoding JWT tokens and fetching the "current user" for
   protected routes (get_current_user).

How the flow works:
    Register  -> password is hashed, never stored in plain text
    Login     -> password verified against hash -> JWT token issued
    Requests  -> client sends "Authorization: Bearer <token>" header
                 -> get_current_user() decodes it and loads the user
                    from the database
"""

import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from database import get_db
import models

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# tokenUrl points to our login route - used by FastAPI's auto docs (Swagger UI)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def hash_password(password: str) -> str:
    """Turn a plain text password into a bcrypt hash for storage."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain text password against the stored bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Build a signed JWT token.
    `data` is usually {"sub": user_email} — "sub" (subject) is the
    standard JWT field for "who this token belongs to".
    """
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Dependency used on every protected route.
    FastAPI extracts the Bearer token from the request header,
    passes it here, we decode it, pull out the user's email,
    and load that user from the database.

    If anything is wrong (bad token, expired, user deleted),
    we raise 401 Unauthorized.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user
