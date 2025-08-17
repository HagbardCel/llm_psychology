"""JWT session token management."""

import jwt
import os
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from models.auth_models import TokenValidationResult, SessionInfo


class SessionManager:
    """Manages JWT session tokens and active sessions."""
    
    def __init__(self, secret_key: Optional[str] = None):
        """Initialize session manager with secret key."""
        self.secret_key = secret_key or self._get_or_create_secret()
        self.algorithm = "HS256"
        self.default_expiry_hours = 24
        self.sessions_file = "data/active_sessions.json"
        
        # Ensure data directory exists
        os.makedirs("data", exist_ok=True)
    
    def _get_or_create_secret(self) -> str:
        """Get existing secret or create new one."""
        secret_file = "data/jwt_secret.key"
        
        if os.path.exists(secret_file):
            with open(secret_file, 'r') as f:
                return f.read().strip()
        else:
            # Generate secure random secret
            import secrets
            secret = secrets.token_hex(32)
            with open(secret_file, 'w') as f:
                f.write(secret)
            return secret
    
    def create_token(self, username: str, expiry_hours: int = None) -> str:
        """Create JWT token for user."""
        if expiry_hours is None:
            expiry_hours = self.default_expiry_hours
        
        now = datetime.utcnow()
        exp = now + timedelta(hours=expiry_hours)
        
        payload = {
            'username': username,
            'iat': now,
            'exp': exp,
            'type': 'session'
        }
        
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        
        # Store active session
        self._store_session(username, token, now, exp)
        
        return token
    
    def validate_token(self, token: str) -> TokenValidationResult:
        """Validate JWT token."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            
            # Check if session is still active
            if not self._is_session_active(payload['username'], token):
                return TokenValidationResult(
                    valid=False,
                    error="Session not active"
                )
            
            return TokenValidationResult(
                valid=True,
                payload=payload
            )
            
        except jwt.ExpiredSignatureError:
            return TokenValidationResult(
                valid=False,
                expired=True,
                error="Token expired"
            )
        except jwt.InvalidTokenError:
            return TokenValidationResult(
                valid=False,
                error="Invalid token"
            )
    
    def invalidate_token(self, token: str) -> bool:
        """Invalidate a token by removing from active sessions."""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm], options={"verify_exp": False})
            username = payload.get('username')
            if username:
                self._remove_session(username, token)
                return True
        except:
            pass
        return False
    
    def _store_session(self, username: str, token: str, created_at: datetime, expires_at: datetime):
        """Store active session info."""
        sessions = self._load_sessions()
        
        session_info = {
            'username': username,
            'token': token,
            'created_at': created_at.isoformat(),
            'expires_at': expires_at.isoformat(),
            'last_activity': datetime.utcnow().isoformat()
        }
        
        sessions[f"{username}:{token[-8:]}"] = session_info
        self._save_sessions(sessions)
    
    def _load_sessions(self) -> Dict[str, Any]:
        """Load active sessions from file."""
        try:
            if os.path.exists(self.sessions_file):
                with open(self.sessions_file, 'r') as f:
                    return json.load(f)
        except:
            pass
        return {}
    
    def _save_sessions(self, sessions: Dict[str, Any]):
        """Save active sessions to file."""
        try:
            with open(self.sessions_file, 'w') as f:
                json.dump(sessions, f, indent=2)
        except Exception as e:
            print(f"Failed to save sessions: {e}")
    
    def _is_session_active(self, username: str, token: str) -> bool:
        """Check if session is in active sessions."""
        sessions = self._load_sessions()
        session_key = f"{username}:{token[-8:]}"
        return session_key in sessions
    
    def _remove_session(self, username: str, token: str):
        """Remove session from active sessions."""
        sessions = self._load_sessions()
        session_key = f"{username}:{token[-8:]}"
        if session_key in sessions:
            del sessions[session_key]
            self._save_sessions(sessions)
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions from storage."""
        sessions = self._load_sessions()
        now = datetime.utcnow()
        
        expired_keys = []
        for key, session in sessions.items():
            try:
                expires_at = datetime.fromisoformat(session['expires_at'])
                if now > expires_at:
                    expired_keys.append(key)
            except:
                expired_keys.append(key)  # Remove malformed entries
        
        for key in expired_keys:
            del sessions[key]
        
        if expired_keys:
            self._save_sessions(sessions)
