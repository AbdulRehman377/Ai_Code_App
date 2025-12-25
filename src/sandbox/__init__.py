"""
Sandbox module for executing and previewing generated code in isolated Docker containers.

Components:
- executor: Run code and capture output (immediate execution)
- preview: Host web applications with exposed ports (long-running)
- registry: Track and manage running containers with TTL
"""

from src.sandbox.executor import run_sandbox, ExecutionResult, is_execution_supported
from src.sandbox.preview import (
    start_preview, 
    stop_preview, 
    get_preview_status,
    get_container_logs,
    is_previewable,
    detect_framework,
    PreviewResult,
)
from src.sandbox.registry import (
    PreviewContainer,
    get_registry,
    get_session_container,
    cleanup_expired,
)

__all__ = [
    # Executor
    "run_sandbox",
    "ExecutionResult", 
    "is_execution_supported",
    # Preview
    "start_preview",
    "stop_preview",
    "get_preview_status",
    "get_container_logs",
    "is_previewable",
    "detect_framework",
    "PreviewResult",
    # Registry
    "PreviewContainer",
    "get_registry",
    "get_session_container",
    "cleanup_expired",
]
