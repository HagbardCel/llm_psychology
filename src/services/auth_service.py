"""Authentication service for JWT token management and password handling."""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

import jwt
from passlib.context import CryptContext

from models.auth_models import (
    LoginResponse,
    TokenPayload,
    UserCredentials,
    UserInfo,
)

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling authentication and authorization."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_expire_minutes: int = 60,
    ):
        """
        Initialize the authentication service.

        Args:
            secret_key: Secret key for JWT encoding/decoding
            algorithm: JWT algorithm to use
            access_token_expire_minutes: Token expiration time in minutes
        """
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Hashed password
        """
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against a hash.

        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password to compare against

        Returns:
            True if password matches, False otherwise
        """
        return self.pwd_context.verify(plain_password, hashed_password)

    def create_access_token(
        self, user_id: str, username: str, expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create a JWT access token.

        Args:
            user_id: User ID to encode in token
            username: Username to encode in token
            expires_delta: Optional custom expiration time

        Returns:
            Encoded JWT token
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.access_token_expire_minutes)

        now = datetime.utcnow()
        expire = now + expires_delta

        payload = TokenPayload(
            user_id=user_id,
            username=username,
            exp=int(expire.timestamp()),
            iat=int(now.timestamp()),
        )

        encoded_jwt = jwt.encode(
            payload.model_dump(), self.secret_key, algorithm=self.algorithm
        )
        return encoded_jwt

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token to verify

        Returns:
            TokenPayload if valid, None otherwise
        """
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return TokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None

    def create_login_response(
        self, user_id: str, username: str
    ) -> LoginResponse:
        """
        Create a login response with access token.

        Args:
            user_id: User ID
            username: Username

        Returns:
            LoginResponse with token and metadata
        """
        access_token = self.create_access_token(user_id, username)
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=self.access_token_expire_minutes * 60,  # Convert to seconds
        )

    @staticmethod
    def generate_user_id() -> str:
        """
        Generate a unique user ID.

        Returns:
            Unique user ID string
        """
        return str(uuid.uuid4())

    @staticmethod
    def credentials_to_user_info(credentials: UserCredentials) -> UserInfo:
        """
        Convert UserCredentials to UserInfo (removes sensitive data).

        Args:
            credentials: User credentials with password hash

        Returns:
            UserInfo without sensitive data
        """
        return UserInfo(
            user_id=credentials.user_id,
            username=credentials.username,
            created_at=credentials.created_at,
            last_login=credentials.last_login,
        )
