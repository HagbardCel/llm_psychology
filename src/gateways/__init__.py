"""
Gateway implementations for different client interfaces.

This module provides gateway classes that connect client interfaces
to the orchestration layer.
"""

from .websocket_gateway import WebSocketGateway

__all__ = ["WebSocketGateway"]
