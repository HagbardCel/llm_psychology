"""
Unit tests for TrioServer to ensure proper initialization.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import trio

from psychoanalyst_app.trio_server import TrioServer


class TestTrioServer:
    """Test TrioServer initialization and startup."""

    @pytest.fixture
    def mock_container(self):
        """Create a mock service container."""
        container = MagicMock()

        # Mock Config
        mock_config = MagicMock()
        mock_config.CORS_ALLOWED_ORIGINS = ["*"]

        container.config = mock_config

        # Mock database service
        db_service = AsyncMock()
        db_service.initialize = AsyncMock()
        db_service.health_check = AsyncMock(return_value=True)
        # Ensure background enrichment worker idles during unit tests
        db_service.claim_next_session_enrichment_job = AsyncMock(return_value=None)

        # Setup get() to return appropriate mocks
        def get_service(name):
            if name == "trio_db_service":
                return db_service
            elif name == "llm_service":
                return Mock()
            elif name == "rag_service":
                return Mock()
            return Mock()

        container.get = Mock(side_effect=get_service)
        return container

    @pytest.mark.trio
    async def test_server_initializes_database_service(self, mock_container):
        """Test that server initializes database service before serving."""
        server = TrioServer(mock_container, host="127.0.0.1", port=8888)

        # Mock the serve function to prevent actual server startup
        with patch("psychoanalyst_app.trio_server.serve", new_callable=AsyncMock):
            # Use trio.testing to start the server and cancel it quickly
            async with trio.open_nursery() as nursery:

                async def run_and_cancel():
                    # Give the server a moment to initialize
                    await trio.sleep(0.1)
                    # Cancel the server
                    nursery.cancel_scope.cancel()

                nursery.start_soon(run_and_cancel)

                try:
                    await server.run()
                except trio.Cancelled:
                    pass

            # Verify that db_service.initialize() was called
            db_service = mock_container.get("trio_db_service")
            db_service.initialize.assert_called_once()

    @pytest.mark.trio
    async def test_server_health_check_after_initialization(self, mock_container):
        """Test that health check endpoint works after initialization."""
        server = TrioServer(mock_container, host="127.0.0.1", port=8889)

        # Initialize database manually for this test
        db_service = mock_container.get("trio_db_service")
        await db_service.initialize()

        # Call the health check endpoint within app context
        async with server.app.app_context():
            result = await server._health_check()

            # Check the response format
            response_data = await result.get_json()
            assert response_data["status"] == "healthy"
            assert response_data["database"] == "healthy"
            assert response_data["service"] == "therapy-backend-trio"

    @pytest.mark.trio
    async def test_database_initialization_order(self, mock_container):
        """Test that database is initialized before orchestration."""
        server = TrioServer(mock_container, host="127.0.0.1", port=8890)

        call_order = []

        # Track when db_service.initialize() is called
        db_service = mock_container.get("trio_db_service")
        original_init = db_service.initialize

        async def tracked_init():
            call_order.append("db_init")
            return await original_init()

        db_service.initialize = AsyncMock(side_effect=tracked_init)

        # Mock the serve function
        with patch("psychoanalyst_app.trio_server.serve", new_callable=AsyncMock):
            # Mock _initialize_orchestration to track call order
            original_init_orchestration = server._initialize_orchestration

            def tracked_orchestration(nursery):
                call_order.append("orchestration_init")
                return original_init_orchestration(nursery)

            server._initialize_orchestration = Mock(side_effect=tracked_orchestration)

            # Start and quickly cancel the server
            async with trio.open_nursery() as nursery:

                async def run_and_cancel():
                    await trio.sleep(0.1)
                    nursery.cancel_scope.cancel()

                nursery.start_soon(run_and_cancel)

                try:
                    await server.run()
                except trio.Cancelled:
                    pass

            # Verify database was initialized before orchestration
            assert call_order == ["db_init", "orchestration_init"]
