"""
REST API server for the Virtual LLM-Driven Psychoanalyst application.
Provides HTTP endpoints for UI clients to interact with the therapy backend.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import json

from aiohttp import web, web_runner
from aiohttp.web import middleware
from aiohttp_cors import setup as cors_setup, ResourceOptions

from services.db_service import UserStatus
from container.service_container import ServiceContainer
from context.user_context import UserContext
from exceptions import (
    ConfigurationError, DatabaseError, AgentError, 
    LLMServiceError, RAGServiceError, PsychoanalystError
)


logger = logging.getLogger(__name__)


class APIServer:
    """REST API server for therapy backend services."""
    
    def __init__(self, container: ServiceContainer, host: str = "0.0.0.0", port: int = 8000):
        self.container = container
        self.host = host
        self.port = port
        self.app = web.Application(middlewares=[self._error_middleware])
        self.runner: Optional[web_runner.AppRunner] = None
        
        # Setup CORS
        cors = cors_setup(self.app, defaults={
            "*": ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })
        
        # Setup routes
        self._setup_routes()
        
    def _setup_routes(self):
        """Setup API routes."""
        # Health check
        self.app.router.add_get('/health', self._health_check)
        
        # User management
        self.app.router.add_get('/api/user/status', self._get_user_status)
        self.app.router.add_post('/api/user/profile', self._create_user_profile)
        
        # Session management
        self.app.router.add_get('/api/sessions', self._get_sessions)
        self.app.router.add_get('/api/sessions/{session_id}', self._get_session)
        self.app.router.add_post('/api/sessions', self._create_session)
        
        # Therapy operations
        self.app.router.add_post('/api/therapy/intake', self._conduct_intake)
        self.app.router.add_post('/api/therapy/assessment', self._conduct_assessment)
        self.app.router.add_get('/api/therapy/styles', self._get_therapy_styles)
        self.app.router.add_post('/api/therapy/plan', self._create_therapy_plan)
        
        # Message operations
        self.app.router.add_post('/api/messages/send', self._send_message)
        
    @middleware
    async def _error_middleware(self, request: web.Request, handler):
        """Error handling middleware."""
        try:
            return await handler(request)
        except Exception as e:
            logger.error(f"API error: {e}", exc_info=True)
            
            if isinstance(e, (ConfigurationError, DatabaseError, AgentError, 
                             LLMServiceError, RAGServiceError, PsychoanalystError)):
                return web.json_response(
                    {'error': str(e), 'type': type(e).__name__},
                    status=400
                )
            else:
                return web.json_response(
                    {'error': 'Internal server error'},
                    status=500
                )
    
    def _get_user_context(self, request: web.Request) -> UserContext:
        """Extract user context from request."""
        # TODO: Implement proper authentication and user extraction
        # For now, use a default user
        user_id = request.headers.get('X-User-ID', 'default_user')
        return UserContext(user_id)
    
    async def _health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'therapy-backend'
        })
    
    async def _get_user_status(self, request: web.Request) -> web.Response:
        """Get user status endpoint."""
        try:
            user_context = self._get_user_context(request)
            db_service = self.container.get('db_service')
            
            status = db_service.get_user_status()
            
            return web.json_response({
                'user_id': user_context.user_id,
                'status': status.value,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            raise
    
    async def _create_user_profile(self, request: web.Request) -> web.Response:
        """Create user profile endpoint."""
        try:
            user_context = self._get_user_context(request)
            data = await request.json()
            
            # TODO: Implement user profile creation
            # For now, just return success
            return web.json_response({
                'user_id': user_context.user_id,
                'profile_created': True,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error creating user profile: {e}")
            raise
    
    async def _get_sessions(self, request: web.Request) -> web.Response:
        """Get user sessions endpoint."""
        try:
            user_context = self._get_user_context(request)
            db_service = self.container.get('db_service')
            
            sessions = db_service.get_all_sessions_for_user()
            
            sessions_data = []
            for session in sessions:
                sessions_data.append({
                    'id': session.id,
                    'agent_type': session.agent_type.value,
                    'start_time': session.start_time.isoformat(),
                    'end_time': session.end_time.isoformat() if session.end_time else None,
                    'message_count': len(session.messages)
                })
            
            return web.json_response({
                'sessions': sessions_data,
                'count': len(sessions_data)
            })
            
        except Exception as e:
            logger.error(f"Error getting sessions: {e}")
            raise
    
    async def _get_session(self, request: web.Request) -> web.Response:
        """Get specific session endpoint."""
        try:
            session_id = request.match_info['session_id']
            user_context = self._get_user_context(request)
            db_service = self.container.get('db_service')
            
            # TODO: Implement session retrieval by ID
            return web.json_response({
                'session_id': session_id,
                'message': 'Session retrieval not yet implemented'
            })
            
        except Exception as e:
            logger.error(f"Error getting session: {e}")
            raise
    
    async def _create_session(self, request: web.Request) -> web.Response:
        """Create new session endpoint."""
        try:
            user_context = self._get_user_context(request)
            data = await request.json()
            session_type = data.get('type', 'therapy')
            
            # TODO: Implement session creation
            return web.json_response({
                'session_id': f"session_{datetime.now().timestamp()}",
                'type': session_type,
                'created': True,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            raise
    
    async def _conduct_intake(self, request: web.Request) -> web.Response:
        """Conduct intake process endpoint."""
        try:
            user_context = self._get_user_context(request)
            data = await request.json()
            
            # TODO: Implement intake process via API
            return web.json_response({
                'intake_completed': False,
                'message': 'Intake via API not yet implemented'
            })
            
        except Exception as e:
            logger.error(f"Error conducting intake: {e}")
            raise
    
    async def _conduct_assessment(self, request: web.Request) -> web.Response:
        """Conduct assessment endpoint."""
        try:
            user_context = self._get_user_context(request)
            data = await request.json()
            
            # TODO: Implement assessment process via API
            return web.json_response({
                'assessment_completed': False,
                'message': 'Assessment via API not yet implemented'
            })
            
        except Exception as e:
            logger.error(f"Error conducting assessment: {e}")
            raise
    
    async def _get_therapy_styles(self, request: web.Request) -> web.Response:
        """Get available therapy styles endpoint."""
        try:
            style_service = self.container.get('style_service')
            available_styles = style_service.get_available_styles()
            
            styles_data = []
            for style_id in available_styles:
                description = style_service.get_style_description(style_id)
                styles_data.append({
                    'id': style_id,
                    'name': style_id.upper(),
                    'description': description
                })
            
            return web.json_response({
                'styles': styles_data,
                'count': len(styles_data)
            })
            
        except Exception as e:
            logger.error(f"Error getting therapy styles: {e}")
            raise
    
    async def _create_therapy_plan(self, request: web.Request) -> web.Response:
        """Create therapy plan endpoint."""
        try:
            user_context = self._get_user_context(request)
            data = await request.json()
            
            # TODO: Implement therapy plan creation
            return web.json_response({
                'plan_created': False,
                'message': 'Therapy plan creation via API not yet implemented'
            })
            
        except Exception as e:
            logger.error(f"Error creating therapy plan: {e}")
            raise
    
    async def _send_message(self, request: web.Request) -> web.Response:
        """Send message endpoint (for non-WebSocket communication)."""
        try:
            user_context = self._get_user_context(request)
            data = await request.json()
            message = data.get('message', '')
            
            if not message:
                return web.json_response(
                    {'error': 'Message content required'},
                    status=400
                )
            
            # TODO: Process message through appropriate agent
            return web.json_response({
                'message_received': True,
                'response': f"Echo: {message}",
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            raise
    
    async def start(self):
        """Start the API server."""
        try:
            self.runner = web_runner.AppRunner(self.app)
            await self.runner.setup()
            
            site = web_runner.TCPSite(self.runner, self.host, self.port)
            await site.start()
            
            logger.info(f"API server started on {self.host}:{self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start API server: {e}")
            raise
    
    async def stop(self):
        """Stop the API server."""
        try:
            if self.runner:
                await self.runner.cleanup()
            logger.info("API server stopped")
            
        except Exception as e:
            logger.error(f"Error stopping API server: {e}")


async def run_api_server(container: ServiceContainer, host: str = "0.0.0.0", port: int = 8000):
    """Run the API server as a standalone service."""
    server = APIServer(container, host, port)
    
    try:
        await server.start()
        logger.info(f"API server running on {host}:{port}")
        
        # Keep server running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await server.stop()


if __name__ == "__main__":
    # This allows running the API server standalone for testing
    from config import Config
    
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Create container
    container = ServiceContainer(Config)
    
    # Run the server
    asyncio.run(run_api_server(container))
