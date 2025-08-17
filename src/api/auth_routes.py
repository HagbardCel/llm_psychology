"""Authentication API routes."""

import logging
from aiohttp import web
from datetime import datetime

from auth.local_auth_service import LocalAuthService
from models.user import CreateUserRequest, LoginRequest
from models.auth_models import AuthResult


logger = logging.getLogger(__name__)


class AuthRoutes:
    """Authentication API route handlers."""
    
    def __init__(self):
        """Initialize authentication routes."""
        self.auth_service = LocalAuthService()
    
    def setup_routes(self, app: web.Application):
        """Setup authentication routes on the app."""
        app.router.add_post('/auth/register', self.register)
        app.router.add_post('/auth/login', self.login)
        app.router.add_post('/auth/logout', self.logout)
        app.router.add_get('/auth/verify', self.verify_token)
        app.router.add_post('/auth/refresh', self.refresh_token)
    
    async def register(self, request: web.Request) -> web.Response:
        """User registration endpoint."""
        try:
            data = await request.json()
            
            # Validate required fields
            required_fields = ['username', 'password', 'fullName']
            for field in required_fields:
                if field not in data:
                    return web.json_response(
                        {'success': False, 'message': f'Missing field: {field}'},
                        status=400
                    )
            
            # Create request object
            register_request = CreateUserRequest(
                username=data['username'],
                password=data['password'],
                full_name=data['fullName'],
                email=data.get('email')
            )
            
            # Register user
            result = self.auth_service.register_user(register_request)
            
            status_code = 201 if result.success else 400
            return web.json_response(
                {
                    'success': result.success,
                    'message': result.message,
                    'userId': result.user_id
                },
                status=status_code
            )
            
        except Exception as e:
            logger.error(f"Registration endpoint error: {e}")
            return web.json_response(
                {'success': False, 'message': 'Registration failed'},
                status=500
            )
    
    async def login(self, request: web.Request) -> web.Response:
        """User login endpoint."""
        try:
            data = await request.json()
            
            # Validate required fields
            if 'username' not in data or 'password' not in data:
                return web.json_response(
                    {'success': False, 'message': 'Username and password required'},
                    status=400
                )
            
            # Create login request
            login_request = LoginRequest(
                username=data['username'],
                password=data['password']
            )
            
            # Authenticate user
            result = self.auth_service.login_user(login_request)
            
            response_data = {
                'success': result.success,
                'message': result.message
            }
            
            if result.success:
                response_data['token'] = result.token
                response_data['user'] = result.user_info
            
            status_code = 200 if result.success else 401
            return web.json_response(response_data, status=status_code)
            
        except Exception as e:
            logger.error(f"Login endpoint error: {e}")
            return web.json_response(
                {'success': False, 'message': 'Login failed'},
                status=500
            )
    
    async def logout(self, request: web.Request) -> web.Response:
        """User logout endpoint."""
        try:
            # Get token from Authorization header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return web.json_response(
                    {'success': False, 'message': 'Invalid authorization header'},
                    status=400
                )
            
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            
            # Logout user
            success = self.auth_service.logout_user(token)
            
            return web.json_response({
                'success': success,
                'message': 'Logged out successfully' if success else 'Logout failed'
            })
            
        except Exception as e:
            logger.error(f"Logout endpoint error: {e}")
            return web.json_response(
                {'success': False, 'message': 'Logout failed'},
                status=500
            )
    
    async def verify_token(self, request: web.Request) -> web.Response:
        """Token verification endpoint."""
        try:
            # Get token from Authorization header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return web.json_response(
                    {'valid': False, 'message': 'Invalid authorization header'},
                    status=400
                )
            
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            
            # Validate token
            is_valid = self.auth_service.validate_token(token)
            
            return web.json_response({
                'valid': is_valid,
                'message': 'Token is valid' if is_valid else 'Token is invalid'
            })
            
        except Exception as e:
            logger.error(f"Token verification error: {e}")
            return web.json_response(
                {'valid': False, 'message': 'Verification failed'},
                status=500
            )
    
    async def refresh_token(self, request: web.Request) -> web.Response:
        """Token refresh endpoint."""
        try:
            # Get token from Authorization header
            auth_header = request.headers.get('Authorization', '')
            if not auth_header.startswith('Bearer '):
                return web.json_response(
                    {'success': False, 'message': 'Invalid authorization header'},
                    status=400
                )
            
            token = auth_header[7:]  # Remove 'Bearer ' prefix
            
            # Validate current token
            validation_result = self.auth_service.session_manager.validate_token(token)
            if not validation_result.valid:
                return web.json_response(
                    {'success': False, 'message': 'Invalid token'},
                    status=401
                )
            
            # Create new token
            username = validation_result.payload['username']
            new_token = self.auth_service.session_manager.create_token(username)
            
            # Invalidate old token
            self.auth_service.logout_user(token)
            
            return web.json_response({
                'success': True,
                'message': 'Token refreshed',
                'token': new_token
            })
            
        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return web.json_response(
                {'success': False, 'message': 'Token refresh failed'},
                status=500
            )
