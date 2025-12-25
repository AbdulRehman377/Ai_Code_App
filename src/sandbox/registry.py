"""
Container Registry - Track running preview containers with TTL management.

Responsibilities:
- Store container info (id, port, start_time, session)
- Allocate and release ports
- Track TTL and cleanup expired containers
- Provide container lookup and management
"""

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

try:
    import docker  # type: ignore[import-not-found]
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False


# =============================================================================
# CONFIGURATION
# =============================================================================

# Port range for preview containers
PORT_RANGE_START = 8100
PORT_RANGE_END = 8200

# Default TTL for preview containers (15 minutes)
DEFAULT_TTL_MINUTES = 15

# Registry file location
REGISTRY_FILE = Path(__file__).parent.parent.parent / ".preview_registry.json"


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PreviewContainer:
    """Information about a running preview container."""
    container_id: str
    container_name: str
    port: int
    internal_port: int
    start_time: str  # ISO format
    ttl_minutes: int
    session_id: str
    language: str
    framework: Optional[str]
    url: str
    status: str  # "running", "stopped", "expired"
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PreviewContainer":
        return cls(**data)
    
    def is_expired(self) -> bool:
        """Check if the container has exceeded its TTL."""
        start = datetime.fromisoformat(self.start_time)
        expiry = start + timedelta(minutes=self.ttl_minutes)
        return datetime.now() > expiry
    
    def time_remaining(self) -> int:
        """Get remaining time in seconds."""
        start = datetime.fromisoformat(self.start_time)
        expiry = start + timedelta(minutes=self.ttl_minutes)
        remaining = (expiry - datetime.now()).total_seconds()
        return max(0, int(remaining))
    
    def time_remaining_formatted(self) -> str:
        """Get remaining time as formatted string."""
        seconds = self.time_remaining()
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}m {secs}s"


# =============================================================================
# REGISTRY CLASS
# =============================================================================

class ContainerRegistry:
    """
    Manages the registry of running preview containers.
    
    Thread-safe operations for:
    - Adding/removing containers
    - Port allocation
    - TTL-based cleanup
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern for registry."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._file_lock = threading.Lock()
        self._containers: Dict[str, PreviewContainer] = {}
        self._load_registry()
        self._initialized = True
        
        # Start background cleanup thread
        self._start_cleanup_thread()
    
    def _load_registry(self):
        """Load registry from file."""
        if REGISTRY_FILE.exists():
            try:
                with open(REGISTRY_FILE, 'r') as f:
                    data = json.load(f)
                    self._containers = {
                        k: PreviewContainer.from_dict(v) 
                        for k, v in data.items()
                    }
            except (json.JSONDecodeError, Exception):
                self._containers = {}
        else:
            self._containers = {}
    
    def _save_registry(self):
        """Save registry to file."""
        with self._file_lock:
            try:
                data = {k: v.to_dict() for k, v in self._containers.items()}
                with open(REGISTRY_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
            except Exception:
                pass  # Fail silently
    
    def _start_cleanup_thread(self):
        """Start background thread for periodic cleanup."""
        def cleanup_loop():
            while True:
                time.sleep(60)  # Check every minute
                self.cleanup_expired()
        
        thread = threading.Thread(target=cleanup_loop, daemon=True)
        thread.start()
    
    def allocate_port(self) -> Optional[int]:
        """
        Allocate an available port from the range.
        
        Returns:
            Available port number, or None if all ports are in use
        """
        used_ports = {c.port for c in self._containers.values() if c.status == "running"}
        
        for port in range(PORT_RANGE_START, PORT_RANGE_END):
            if port not in used_ports:
                # Double-check port is actually free on the system
                if self._is_port_free(port):
                    return port
        
        return None
    
    def _is_port_free(self, port: int) -> bool:
        """Check if a port is free on the system."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('localhost', port))
                return True
            except OSError:
                return False
    
    def register_container(self, container: PreviewContainer) -> None:
        """Register a new preview container."""
        with self._lock:
            self._containers[container.container_id] = container
            self._save_registry()
    
    def unregister_container(self, container_id: str) -> Optional[PreviewContainer]:
        """Remove a container from the registry."""
        with self._lock:
            container = self._containers.pop(container_id, None)
            self._save_registry()
            return container
    
    def get_container(self, container_id: str) -> Optional[PreviewContainer]:
        """Get container info by ID."""
        return self._containers.get(container_id)
    
    def get_container_by_session(self, session_id: str) -> Optional[PreviewContainer]:
        """Get the active container for a session (running or starting)."""
        for container in self._containers.values():
            if container.session_id == session_id and container.status in ("running", "starting"):
                return container
        return None
    
    def get_all_containers(self) -> List[PreviewContainer]:
        """Get all registered containers."""
        return list(self._containers.values())
    
    def get_running_containers(self) -> List[PreviewContainer]:
        """Get all currently running containers."""
        return [c for c in self._containers.values() if c.status == "running"]
    
    def update_status(self, container_id: str, status: str) -> None:
        """Update a container's status."""
        with self._lock:
            if container_id in self._containers:
                self._containers[container_id].status = status
                self._save_registry()
    
    def cleanup_expired(self) -> List[str]:
        """
        Stop and remove expired containers.
        
        Returns:
            List of cleaned up container IDs
        """
        if not DOCKER_AVAILABLE:
            return []
        
        cleaned = []
        
        try:
            client = docker.from_env()
        except Exception:
            return []
        
        with self._lock:
            expired = [c for c in self._containers.values() 
                      if c.status == "running" and c.is_expired()]
            
            for container in expired:
                try:
                    # Stop and remove the Docker container
                    docker_container = client.containers.get(container.container_id)
                    docker_container.stop(timeout=5)
                    docker_container.remove(force=True)
                except Exception:
                    pass
                
                # Update registry
                container.status = "expired"
                cleaned.append(container.container_id)
            
            self._save_registry()
        
        return cleaned
    
    def stop_container(self, container_id: str) -> bool:
        """
        Manually stop a preview container.
        
        Returns:
            True if stopped successfully, False otherwise
        """
        if not DOCKER_AVAILABLE:
            return False
        
        container = self.get_container(container_id)
        if not container:
            return False
        
        try:
            client = docker.from_env()
            docker_container = client.containers.get(container_id)
            docker_container.stop(timeout=5)
            docker_container.remove(force=True)
            
            self.update_status(container_id, "stopped")
            return True
            
        except Exception:
            self.update_status(container_id, "stopped")
            return False
    
    def stop_session_containers(self, session_id: str) -> int:
        """
        Stop all containers for a session.
        
        Returns:
            Number of containers stopped
        """
        count = 0
        for container in list(self._containers.values()):
            if container.session_id == session_id and container.status == "running":
                if self.stop_container(container.container_id):
                    count += 1
        return count
    
    def cleanup_all(self) -> int:
        """
        Stop and remove all preview containers.
        
        Returns:
            Number of containers cleaned up
        """
        count = 0
        for container_id in list(self._containers.keys()):
            if self.stop_container(container_id):
                count += 1
        return count


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

def get_registry() -> ContainerRegistry:
    """Get the singleton registry instance."""
    return ContainerRegistry()


def allocate_port() -> Optional[int]:
    """Allocate a port from the registry."""
    return get_registry().allocate_port()


def register_container(container: PreviewContainer) -> None:
    """Register a container in the registry."""
    get_registry().register_container(container)


def stop_container(container_id: str) -> bool:
    """Stop a container by ID."""
    return get_registry().stop_container(container_id)


def get_session_container(session_id: str) -> Optional[PreviewContainer]:
    """Get the running container for a session."""
    return get_registry().get_container_by_session(session_id)


def cleanup_expired() -> List[str]:
    """Cleanup expired containers."""
    return get_registry().cleanup_expired()


def cleanup_stale_entries() -> int:
    """Remove entries for containers that no longer exist or are stopped/expired."""
    registry = get_registry()
    count = 0
    
    for container_id in list(registry._containers.keys()):
        container = registry._containers[container_id]
        if container.status in ("stopped", "expired"):
            registry._containers.pop(container_id, None)
            count += 1
    
    registry._save_registry()
    return count

