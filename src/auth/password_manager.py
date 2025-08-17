"""Password security manager with bcrypt hashing."""

import bcrypt
import re
from typing import Tuple, List


class PasswordManager:
    """Handles password hashing, verification, and validation."""
    
    # Cost factor for bcrypt (minimum 12 for security)
    COST_FACTOR = 12
    MIN_LENGTH = 8
    MAX_LENGTH = 128
    
    def hash_password(self, password: str) -> str:
        """Hash password using bcrypt with salt."""
        if len(password) < self.MIN_LENGTH:
            raise ValueError(f"Password must be at least {self.MIN_LENGTH} characters")
        
        salt = bcrypt.gensalt(rounds=self.COST_FACTOR)
        password_bytes = password.encode('utf-8')
        hashed = bcrypt.hashpw(password_bytes, salt)
        return hashed.decode('utf-8')
    
    def verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password against stored hash."""
        try:
            password_bytes = password.encode('utf-8')
            hash_bytes = password_hash.encode('utf-8')
            return bcrypt.checkpw(password_bytes, hash_bytes)
        except Exception:
            return False
    
    def validate_password(self, password: str) -> bool:
        """Validate password against security requirements."""
        if not password:
            return False
        return self.MIN_LENGTH <= len(password) <= self.MAX_LENGTH
    
    def get_password_requirements(self) -> List[str]:
        """Get list of password requirements."""
        return [
            f"At least {self.MIN_LENGTH} characters long",
            f"No longer than {self.MAX_LENGTH} characters",
            "Recommended: Mix of uppercase, lowercase, numbers, and symbols"
        ]
