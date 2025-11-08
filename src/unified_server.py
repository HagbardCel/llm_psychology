#!/usr/bin/env python3
"""
Unified server combining HTTP API and WebSocket functionality.
Runs both services on the same port for simplified deployment.
"""

import asyncio
import logging
from typing import Optional
from datetime import datetime

from aiohttp import web
from aiohttp.web import middleware
from aiohttp_cors import setup as cors_setup, ResourceOptions
import socketio

from websocket_server.connection_manager import ConnectionManager
from websocket_server.message_handler import MessageHandler
from websocket_server.typing_manager import TypingManager
from container.service_container import ServiceContainer
from config import Config
from src.orchestration.agent_orchestrator import AgentOrchestrator
from src.orchestration.conversation_manager import ConversationManager
from src.orchestration.workflow_engine import WorkflowEngine
from src.gateways.websocket_gateway import WebSocketGateway

logger = logging.getLogger(__name__)


class UnifiedServer:
    """Unified server providing both HTTP API and WebSocket services."""

    def __init__(self, container: ServiceContainer, host: str = "0.0.0.0", port: int = 8000):
        self.container = container
        self.host = host
        self.port = port
        self.runner: Optional[web.AppRunner] = None

        # Create aiohttp application with error middleware
        self.app = web.Application(middlewares=[self._error_middleware])

        # Setup CORS
        cors = cors_setup(self.app, defaults={
            "*": ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })

        # Initialize Socket.IO server
        self.sio = socketio.AsyncServer(
            cors_allowed_origins="*",
            logger=logger,
            engineio_logger=logger,
            async_mode='aiohttp'
        )

        # Attach Socket.IO to aiohttp app
        self.sio.attach(self.app)

        # Initialize orchestration layer
        db_service = container.get_db_service()
        llm_service = container.get_llm_service()
        rag_service = container.get_rag_service()

        workflow_engine = WorkflowEngine(db_service)
        conversation_manager = ConversationManager(llm_service, rag_service, db_service)
        self.orchestrator = AgentOrchestrator(
            container, workflow_engine, conversation_manager
        )

        # Initialize WebSocket components
        self.connection_manager = ConnectionManager()
        self.typing_manager = TypingManager()
        self.websocket_gateway = WebSocketGateway(
            self.sio, self.orchestrator, self.connection_manager
        )
        self.message_handler = MessageHandler(
            self.connection_manager, self.websocket_gateway
        )

        # Setup routes and handlers
        self._setup_http_routes()
        self._setup_websocket_handlers()

        logger.info("Unified server initialized with orchestration layer")

    @middleware
    async def _error_middleware(self, request: web.Request, handler):
        """Error handling middleware."""
        try:
            return await handler(request)
        except Exception as e:
            logger.error(f"API error: {e}", exc_info=True)
            return web.json_response(
                {'error': 'Internal server error', 'details': str(e)},
                status=500
            )

    def _setup_http_routes(self):
        """Setup HTTP API routes."""
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
        self.app.router.add_get('/api/therapy/styles', self._get_therapy_styles)

        logger.info("HTTP routes configured")

    def _setup_websocket_handlers(self):
        """Setup WebSocket event handlers."""

        @self.sio.event
        async def connect(sid, environ, auth):
            """Handle client connection."""
            try:
                # Extract authentication data
                user_id = auth.get("user_id") if auth else None
                auth_token = auth.get("token") if auth else None

                if not user_id or not auth_token:
                    logger.warning(f"Connection rejected from {sid}: Missing auth data")
                    return False

                # Authenticate user
                success = await self.connection_manager.connect_user(sid, user_id, auth_token)
                if not success:
                    logger.warning(f"Connection rejected for user {user_id}")
                    return False

                # Send connection confirmation
                await self.sio.emit("connected", {
                    "status": "connected",
                    "user_id": user_id,
                    "timestamp": datetime.now().isoformat()
                }, room=sid)

                logger.info(f"User {user_id} connected successfully via WebSocket")
                return True

            except Exception as e:
                logger.error(f"Error during connection: {e}")
                return False

        @self.sio.event
        async def disconnect(sid):
            """Handle client disconnection."""
            try:
                user_id = await self.connection_manager.disconnect_user(sid)
                if user_id:
                    # Stop typing if user was typing
                    self.typing_manager.stop_typing(user_id)
                    logger.info(f"User {user_id} disconnected from WebSocket")

            except Exception as e:
                logger.error(f"Error during disconnection: {e}")

        @self.sio.event
        async def message(sid, data):
            """Handle incoming messages."""
            try:
                if not isinstance(data, dict):
                    await self.sio.emit("error", {"error": "Invalid message format"}, room=sid)
                    return

                event_type = data.get("type")
                message_data = data.get("data", {})

                if not event_type:
                    await self.sio.emit("error", {"error": "Missing message type"}, room=sid)
                    return

                # Handle the message
                response = await self.message_handler.handle_message(sid, event_type, message_data)

                if response:
                    await self.sio.emit("response", response, room=sid)

            except Exception as e:
                logger.error(f"Error handling message from {sid}: {e}")
                await self.sio.emit("error", {"error": "Message processing failed"}, room=sid)

        @self.sio.event
        async def typing_start(sid, data):
            """Handle typing start event."""
            try:
                user_id = self.connection_manager.get_user_id(sid)
                if user_id:
                    self.typing_manager.start_typing(user_id)
            except Exception as e:
                logger.error(f"Error handling typing start: {e}")

        @self.sio.event
        async def typing_stop(sid, data):
            """Handle typing stop event."""
            try:
                user_id = self.connection_manager.get_user_id(sid)
                if user_id:
                    self.typing_manager.stop_typing(user_id)
            except Exception as e:
                logger.error(f"Error handling typing stop: {e}")

        @self.sio.event
        async def ping(sid, data):
            """Handle ping for connection testing."""
            await self.sio.emit("pong", {"timestamp": datetime.now().isoformat()}, room=sid)

        logger.info("WebSocket handlers configured")

    # HTTP API endpoint handlers

    async def _health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'service': 'therapy-backend-unified',
            'websocket': {
                'active_connections': self.connection_manager.get_active_connections_count(),
                'typing_users': len(self.typing_manager.get_typing_users())
            }
        })

    async def _get_user_status(self, request: web.Request) -> web.Response:
        """Get user status endpoint."""
        try:
            db_service = self.container.get('db_service')
            status = db_service.get_user_status()

            return web.json_response({
                'user_id': 'default_user',  # TODO: Extract from auth
                'status': status,
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            raise

    async def _create_user_profile(self, request: web.Request) -> web.Response:
        """Create user profile endpoint."""
        return web.json_response({
            'message': 'User profile creation not yet implemented',
            'timestamp': datetime.now().isoformat()
        })

    async def _get_sessions(self, request: web.Request) -> web.Response:
        """Get user sessions endpoint."""
        try:
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
        session_id = request.match_info['session_id']
        return web.json_response({
            'session_id': session_id,
            'message': 'Session retrieval not yet implemented'
        })

    async def _create_session(self, request: web.Request) -> web.Response:
        """Create new session endpoint."""
        data = await request.json()
        session_type = data.get('type', 'therapy')

        return web.json_response({
            'session_id': f"session_{datetime.now().timestamp()}",
            'type': session_type,
            'created': True,
            'timestamp': datetime.now().isoformat()
        })

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

    async def start(self):
        """Start the unified server."""
        try:
            # Start typing manager
            await self.typing_manager.start()

            # Create and start aiohttp runner
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            site = web.TCPSite(self.runner, self.host, self.port)
            await site.start()

            logger.info(f"Unified server (HTTP + WebSocket) started on {self.host}:{self.port}")
            print(f"🚀 Server running on http://{self.host}:{self.port}")
            print(f"   - HTTP API: http://{self.host}:{self.port}/health")
            print(f"   - WebSocket: ws://{self.host}:{self.port}/socket.io/")

        except Exception as e:
            logger.error(f"Failed to start unified server: {e}")
            raise

    async def stop(self):
        """Stop the unified server."""
        try:
            # Stop typing manager
            await self.typing_manager.stop()

            # Stop aiohttp runner
            if self.runner:
                await self.runner.cleanup()

            logger.info("Unified server stopped")

        except Exception as e:
            logger.error(f"Error stopping unified server: {e}")

    async def run_forever(self):
        """Run the server until interrupted."""
        await self.start()

        try:
            # Keep server running
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("Server shutdown requested")
        finally:
            await self.stop()


async def run_unified_server(config=None, host: str = "0.0.0.0", port: int = 8000):
    """Run the unified server as a standalone service."""
    if config is None:
        config = Config

    logger.info(f"Starting {config.APP_NAME} v{config.VERSION} - Unified Server")

    # Initialize service container
    container = ServiceContainer(config)

    # Create and run server
    server = UnifiedServer(container, host, port)

    try:
        await server.run_forever()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
    finally:
        await server.stop()
        container.shutdown()
        logger.info("Server shutdown complete")


if __name__ == "__main__":
    import sys
    from config import setup_logging

    # Setup logging
    setup_logging()

    # Run the unified server
    try:
        asyncio.run(run_unified_server())
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
        sys.exit(0)
