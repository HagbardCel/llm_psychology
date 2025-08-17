"""Local authentication service with user management and security."""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

from models.user import User, CreateUserRequest, LoginRequest, ChangePasswordRequest
from models.auth_models import AuthResult, CreateUserResult, PasswordChangeResult
from auth.password_manager import PasswordManager
from auth.session_manager import SessionManager


logger = logging.getLogger(__name__)


class LocalAuthService:
    """Local authentication service with full user management."""
    
    def __init__(self):
        """Initialize authentication service."""
        self.password_manager = PasswordManager()
        self.session_manager = SessionManager()
        
        # File paths
        self.users_file = "data/users.json"
        self.failed_attempts_file = "data/security/failed_attempts.json"
        self.locked_accounts_file = "data/security/locked_accounts.json"
        
        # Security settings
        self.max_failed_attempts = 5
        self.lockout_duration_minutes = 30
        
        # Ensure directories exist
        os.makedirs("data/security", exist_ok=True)
        
        # Initialize files if they don't exist
        self._ensure_files_exist()
    
    def _ensure_files_exist(self):
        """Ensure all required files exist."""
        files_to_create = [
            self.users_file,
            self.failed_attempts_file,
            self.locked_accounts_file
        ]
        
        for file_path in files_to_create:
            if not os.path.exists(file_path):
                with open(file_path, 'w') as f:
                    json.dump({}, f)
    
    def register_user(self, request: CreateUserRequest) -> CreateUserResult:
        """Register a new user."""
        try:
            # Validate password
            if not self.password_manager.validate_password(request.password):
                return CreateUserResult(
                    success=False,
                    message="Password does not meet requirements"
                )
            
            # Check if user already exists
            if self._user_exists(request.username):
                return CreateUserResult(
                    success=False,
                    message="Username already exists"
                )
            
            # Hash password
            password_hash = self.password_manager.hash_password(request.password)
            
            # Create user
            user = User(
                username=request.username,
                password_hash=password_hash,
                full_name=request.full_name,
                email=request.email
            )
            
            # Save user
            if self._save_user(user):
                logger.info(f"User registered: {request.username}")
                return CreateUserResult(
                    success=True,
                    message="User registered successfully",
                    user_id=request.username
                )
            else:
                return CreateUserResult(
                    success=False,
                    message="Failed to save user"
                )
                
        except Exception as e:
            logger.error(f"Registration error for {request.username}: {e}")
            return CreateUserResult(
                success=False,
                message="Registration failed"
            )
    
    def login_user(self, request: LoginRequest) -> AuthResult:
        """Authenticate user login."""
        try:
            # Check if account is locked
            if self._is_account_locked(request.username):
                return AuthResult(
                    success=False,
                    message="Account is temporarily locked"
                )
            
            # Load user
            user = self._load_user(request.username)
            if not user:
                self._record_failed_attempt(request.username)
                return AuthResult(
                    success=False,
                    message="Invalid username or password"
                )
            
            # Check if user can login
            if not user.can_login():
                return AuthResult(
                    success=False,
                    message="Account is not active or locked"
                )
            
            # Verify password
            if not self.password_manager.verify_password(request.password, user.password_hash):
                self._record_failed_attempt(request.username)
                
                # Check if we should lock account
                failed_count = self._get_failed_attempts(request.username)
                if failed_count >= self.max_failed_attempts:
                    self._lock_account(request.username)
                    return AuthResult(
                        success=False,
                        message="Account locked due to too many failed attempts"
                    )
                
                return AuthResult(
                    success=False,
                    message="Invalid username or password"
                )
            
            # Clear failed attempts on successful login
            self._clear_failed_attempts(request.username)
            
            # Update last login
            user.last_login = datetime.now()
            self._save_user(user)
            
            # Create session token
            token = self.session_manager.create_token(user.username)
            
            logger.info(f"User logged in: {request.username}")
            
            return AuthResult(
                success=True,
                message="Login successful",
                token=token,
                user_info=user.to_safe_dict()
            )
            
        except Exception as e:
            logger.error(f"Login error for {request.username}: {e}")
            return AuthResult(
                success=False,
                message="Login failed"
            )
    
    def logout_user(self, token: str) -> bool:
        """Logout user by invalidating token."""
        try:
            return self.session_manager.invalidate_token(token)
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False
    
    def validate_token(self, token: str) -> bool:
        """Validate if token is valid and active."""
        result = self.session_manager.validate_token(token)
        return result.valid
    
    def _user_exists(self, username: str) -> bool:
        """Check if user exists."""
        return self._load_user(username) is not None
    
    def _load_user(self, username: str) -> Optional[User]:
        """Load user from storage."""
        try:
            if not os.path.exists(self.users_file):
                return None
            
            with open(self.users_file, 'r') as f:
                users_data = json.load(f)
            
            if username not in users_data:
                return None
            
            return User.from_dict(users_data[username])
            
        except Exception as e:
            logger.error(f"Error loading user {username}: {e}")
            return None
    
    def _save_user(self, user: User) -> bool:
        """Save user to storage."""
        try:
            # Load existing users
            users_data = {}
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r') as f:
                    users_data = json.load(f)
            
            # Update user data
            users_data[user.username] = user.to_dict()
            
            # Save back to file
            with open(self.users_file, 'w') as f:
                json.dump(users_data, f, indent=2)
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving user {user.username}: {e}")
            return False
    
    def _record_failed_attempt(self, username: str):
        """Record failed login attempt."""
        try:
            failed_attempts = {}
            if os.path.exists(self.failed_attempts_file):
                with open(self.failed_attempts_file, 'r') as f:
                    failed_attempts = json.load(f)
            
            if username not in failed_attempts:
                failed_attempts[username] = []
            
            failed_attempts[username].append(datetime.now().isoformat())
            
            # Keep only recent attempts (last hour)
            cutoff = datetime.now() - timedelta(hours=1)
            failed_attempts[username] = [
                attempt for attempt in failed_attempts[username]
                if datetime.fromisoformat(attempt) > cutoff
            ]
            
            with open(self.failed_attempts_file, 'w') as f:
                json.dump(failed_attempts, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error recording failed attempt for {username}: {e}")
    
    def _get_failed_attempts(self, username: str) -> int:
        """Get count of recent failed attempts."""
        try:
            if not os.path.exists(self.failed_attempts_file):
                return 0
            
            with open(self.failed_attempts_file, 'r') as f:
                failed_attempts = json.load(f)
            
            if username not in failed_attempts:
                return 0
            
            # Count attempts in last hour
            cutoff = datetime.now() - timedelta(hours=1)
            recent_attempts = [
                attempt for attempt in failed_attempts[username]
                if datetime.fromisoformat(attempt) > cutoff
            ]
            
            return len(recent_attempts)
            
        except Exception as e:
            logger.error(f"Error getting failed attempts for {username}: {e}")
            return 0
    
    def _clear_failed_attempts(self, username: str):
        """Clear failed attempts for user."""
        try:
            if not os.path.exists(self.failed_attempts_file):
                return
            
            with open(self.failed_attempts_file, 'r') as f:
                failed_attempts = json.load(f)
            
            if username in failed_attempts:
                del failed_attempts[username]
                
                with open(self.failed_attempts_file, 'w') as f:
                    json.dump(failed_attempts, f, indent=2)
                    
        except Exception as e:
            logger.error(f"Error clearing failed attempts for {username}: {e}")
    
    def _is_account_locked(self, username: str) -> bool:
        """Check if account is currently locked."""
        try:
            if not os.path.exists(self.locked_accounts_file):
                return False
            
            with open(self.locked_accounts_file, 'r') as f:
                locked_accounts = json.load(f)
            
            if username not in locked_accounts:
                return False
            
            lock_time = datetime.fromisoformat(locked_accounts[username])
            unlock_time = lock_time + timedelta(minutes=self.lockout_duration_minutes)
            
            if datetime.now() > unlock_time:
                # Lock has expired, remove it
                del locked_accounts[username]
                with open(self.locked_accounts_file, 'w') as f:
                    json.dump(locked_accounts, f, indent=2)
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking lock status for {username}: {e}")
            return False
    
    def _lock_account(self, username: str):
        """Lock account due to failed attempts."""
        try:
            locked_accounts = {}
            if os.path.exists(self.locked_accounts_file):
                with open(self.locked_accounts_file, 'r') as f:
                    locked_accounts = json.load(f)
            
            locked_accounts[username] = datetime.now().isoformat()
            
            with open(self.locked_accounts_file, 'w') as f:
                json.dump(locked_accounts, f, indent=2)
            
            logger.warning(f"Account locked: {username}")
            
        except Exception as e:
            logger.error(f"Error locking account {username}: {e}")
