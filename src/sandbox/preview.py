"""
Preview Hosting - Run web applications with exposed ports and URLs.

This module handles:
- Detecting previewable applications (web servers)
- Starting containers with exposed ports
- Returning accessible URLs
- Managing container lifecycle with TTL

Supported Frameworks:
- Python: FastAPI, Flask, Django, Streamlit, Gradio
- Node.js: Express, Next.js, React (dev server), Vue, Angular
"""

import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Literal, Optional, Tuple

try:
    import docker  # type: ignore[import-not-found]
    from docker.errors import ContainerError, ImageNotFound, APIError  # type: ignore[import-not-found]
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from src.schemas import CodeBundle, Plan
from src.sandbox.registry import (
    PreviewContainer, 
    get_registry, 
    allocate_port,
    register_container,
    get_session_container,
    cleanup_stale_entries,
    DEFAULT_TTL_MINUTES,
)


# =============================================================================
# CONSTANTS
# =============================================================================

# Docker images for each language
# Using node:18-slim instead of alpine for better compatibility with native modules
DOCKER_IMAGES = {
    "Python": "python:3.11-slim",
    "python": "python:3.11-slim",
    "JavaScript": "node:18-slim",
    "javascript": "node:18-slim",
    "Node.js": "node:18-slim",
    "node.js": "node:18-slim",
    "nodejs": "node:18-slim",
    "TypeScript": "node:18-slim",
    "typescript": "node:18-slim",
}

# Default ports for frameworks
FRAMEWORK_PORTS = {
    # Python
    "fastapi": 8000,
    "flask": 5000,
    "django": 8000,
    "streamlit": 8501,
    "gradio": 7860,
    # Node.js
    "express": 3000,
    "next": 3000,
    "next.js": 3000,
    "nextjs": 3000,
    "react": 3000,
    "vue": 8080,
    "angular": 4200,
    "nuxt": 3000,
    "koa": 3000,
    "hapi": 3000,
}

# Resource limits for preview containers
MAX_MEMORY_PYTHON = "512m"
MAX_MEMORY_NODEJS = "1g"  # Node.js/React needs more memory for webpack
MAX_CPU = 0.5

# Startup wait time (seconds) - needs to be long enough for npm install + app startup
STARTUP_WAIT = 10  # Initial wait
MAX_STARTUP_WAIT = 60  # Maximum wait for app to be ready
HEALTH_CHECK_INTERVAL = 2  # Check every 2 seconds

# Frameworks that need special handling
SLOW_INSTALL_FRAMEWORKS = {"react", "next", "next.js", "nextjs", "vue", "angular", "nuxt"}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class PreviewResult:
    """Result of starting a preview."""
    status: Literal["starting", "running", "error", "unsupported", "already_running", "stopped", "expired"]
    url: Optional[str] = None
    container_id: Optional[str] = None
    port: Optional[int] = None
    message: Optional[str] = None
    time_remaining: Optional[str] = None
    language: Optional[str] = None
    framework: Optional[str] = None
    logs: Optional[str] = None  # Container logs for debugging
    ready: bool = False  # Whether the app is actually responding
    
    def to_dict(self) -> Dict:
        return {
            "status": self.status,
            "url": self.url,
            "container_id": self.container_id,
            "port": self.port,
            "message": self.message,
            "time_remaining": self.time_remaining,
            "language": self.language,
            "framework": self.framework,
            "logs": self.logs,
            "ready": self.ready,
        }


# =============================================================================
# FRAMEWORK DETECTION
# =============================================================================

def detect_framework(codebundle: CodeBundle, plan: Optional[Plan] = None) -> Optional[str]:
    """
    Detect the web framework being used.
    
    Returns:
        Framework name (lowercase) or None if not a web app
    """
    # First check plan
    if plan and plan.framework:
        return plan.framework.lower()
    
    files = codebundle.files
    
    # Check requirements.txt for Python frameworks
    if "requirements.txt" in files:
        req_content = files["requirements.txt"].lower()
        for framework in ["fastapi", "flask", "django", "streamlit", "gradio"]:
            if framework in req_content:
                return framework
    
    # Check package.json for Node.js frameworks
    if "package.json" in files:
        try:
            pkg = json.loads(files["package.json"])
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            
            # Check for frameworks
            if "next" in deps:
                return "next.js"
            if "express" in deps:
                return "express"
            if "react" in deps or "react-scripts" in deps:
                return "react"
            if "vue" in deps or "@vue/cli-service" in deps:
                return "vue"
            if "@angular/core" in deps:
                return "angular"
            if "nuxt" in deps:
                return "nuxt"
            if "koa" in deps:
                return "koa"
            if "hapi" in deps or "@hapi/hapi" in deps:
                return "hapi"
        except json.JSONDecodeError:
            pass
    
    # Check for Streamlit by looking at file content
    for filename, content in files.items():
        if filename.endswith('.py'):
            if 'import streamlit' in content or 'from streamlit' in content:
                return "streamlit"
            if 'import gradio' in content or 'from gradio' in content:
                return "gradio"
    
    return None


def is_previewable(codebundle: CodeBundle, plan: Optional[Plan] = None) -> bool:
    """Check if the code bundle represents a previewable web application."""
    framework = detect_framework(codebundle, plan)
    return framework is not None


def get_internal_port(framework: Optional[str]) -> int:
    """Get the internal port the app will use."""
    if framework and framework.lower() in FRAMEWORK_PORTS:
        return FRAMEWORK_PORTS[framework.lower()]
    return 8000  # Default


def _wait_for_port(port: int, timeout: int = MAX_STARTUP_WAIT) -> bool:
    """
    Wait for a port to become available (app is listening).
    
    Args:
        port: The port to check
        timeout: Maximum time to wait in seconds
        
    Returns:
        True if port is responding, False if timeout
    """
    import socket
    import urllib.request
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            # Try to connect to the port
            with socket.create_connection(("localhost", port), timeout=2):
                # Connection successful, app is listening
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            # Not ready yet, wait and retry
            time.sleep(HEALTH_CHECK_INTERVAL)
    
    return False


def _cleanup_old_containers(client, container_name: str) -> None:
    """Remove any existing containers with the same name."""
    try:
        existing = client.containers.get(container_name)
        existing.stop(timeout=2)
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass
    except Exception:
        pass


def _check_port_quick(port: int) -> bool:
    """Quick check if a port is responding (non-blocking)."""
    import socket
    try:
        with socket.create_connection(("localhost", port), timeout=1):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


# =============================================================================
# RUN COMMAND BUILDERS
# =============================================================================

def _build_run_command(files: Dict[str, str], language: str, framework: Optional[str]) -> str:
    """Build the command to run the web application."""
    framework_lower = framework.lower() if framework else ""
    
    if language in ("Python", "python"):
        if framework_lower == "fastapi":
            # Find the main file
            main_file = _find_python_main(files)
            return f"uvicorn {main_file.replace('.py', '').replace('/', '.')}:app --host 0.0.0.0 --port 8000"
        
        elif framework_lower == "flask":
            main_file = _find_python_main(files)
            return f"flask --app {main_file.replace('.py', '')} run --host 0.0.0.0 --port 5000"
        
        elif framework_lower == "django":
            return "python manage.py runserver 0.0.0.0:8000"
        
        elif framework_lower == "streamlit":
            main_file = _find_python_main(files)
            return f"streamlit run {main_file} --server.address 0.0.0.0 --server.port 8501 --server.headless true"
        
        elif framework_lower == "gradio":
            main_file = _find_python_main(files)
            return f"python {main_file}"
        
        else:
            # Generic Python with uvicorn
            main_file = _find_python_main(files)
            return f"python {main_file}"
    
    elif language in ("JavaScript", "javascript", "Node.js", "node.js", "nodejs", "TypeScript", "typescript"):
        # React/Next.js/Vue need special handling for host binding
        if framework_lower in ("react", "next", "next.js", "nextjs"):
            # Create React App and Next.js use HOST env var
            # The env var is set in the container, so just run the command
            if "package.json" in files:
                try:
                    pkg = json.loads(files["package.json"])
                    scripts = pkg.get("scripts", {})
                    if "dev" in scripts:
                        return "npm run dev -- --host 0.0.0.0"
                    elif "start" in scripts:
                        return "npm start"
                except json.JSONDecodeError:
                    pass
            return "npm start"
        
        elif framework_lower in ("vue", "angular", "nuxt"):
            # Vue CLI, Angular, and Nuxt
            if "package.json" in files:
                try:
                    pkg = json.loads(files["package.json"])
                    scripts = pkg.get("scripts", {})
                    if "dev" in scripts:
                        return "npm run dev -- --host 0.0.0.0"
                    elif "serve" in scripts:
                        return "npm run serve -- --host 0.0.0.0"
                    elif "start" in scripts:
                        return "npm start"
                except json.JSONDecodeError:
                    pass
            return "npm run dev -- --host 0.0.0.0"
        
        elif framework_lower in ("express", "koa", "hapi", "fastify"):
            # Backend frameworks - just run normally
            if "package.json" in files:
                try:
                    pkg = json.loads(files["package.json"])
                    scripts = pkg.get("scripts", {})
                    if "start" in scripts:
                        return "npm start"
                    elif "dev" in scripts:
                        return "npm run dev"
                except json.JSONDecodeError:
                    pass
            # Default to entry file
            if "index.js" in files:
                return "node index.js"
            elif "server.js" in files:
                return "node server.js"
            elif "app.js" in files:
                return "node app.js"
            return "npm start"
        
        else:
            # Generic Node.js
            if "package.json" in files:
                try:
                    pkg = json.loads(files["package.json"])
                    scripts = pkg.get("scripts", {})
                    if "start" in scripts:
                        return "npm start"
                    elif "dev" in scripts:
                        return "npm run dev"
                except json.JSONDecodeError:
                    pass
            
            # Default to node entry file
            if "index.js" in files:
                return "node index.js"
            elif "server.js" in files:
                return "node server.js"
            elif "app.js" in files:
                return "node app.js"
            
            return "npm start"
    
    return "echo 'Unknown framework'"


def _find_python_main(files: Dict[str, str]) -> str:
    """Find the main Python file."""
    # Priority order
    for name in ["main.py", "app.py", "server.py", "run.py"]:
        if name in files:
            return name
    
    # Find first .py file that's not __init__.py
    for name in files.keys():
        if name.endswith('.py') and name != '__init__.py':
            return name
    
    return "main.py"


def _build_install_command(files: Dict[str, str], language: str, framework: Optional[str]) -> Optional[str]:
    """Build the dependency installation command."""
    framework_lower = framework.lower() if framework else ""
    
    if language in ("Python", "python"):
        # Check for requirements.txt
        if "requirements.txt" in files:
            cmd = "pip install -q -r requirements.txt"
            
            # Add uvicorn for FastAPI if not in requirements
            if framework_lower == "fastapi":
                if "uvicorn" not in files.get("requirements.txt", "").lower():
                    cmd += " uvicorn"
            
            return cmd
        
        # Install framework-specific dependencies
        if framework_lower == "fastapi":
            return "pip install -q fastapi uvicorn"
        elif framework_lower == "flask":
            return "pip install -q flask"
        elif framework_lower == "streamlit":
            return "pip install -q streamlit"
        elif framework_lower == "gradio":
            return "pip install -q gradio"
    
    elif language in ("JavaScript", "javascript", "Node.js", "node.js", "nodejs", "TypeScript", "typescript"):
        if "package.json" in files:
            return "npm install --silent"
    
    return None


# =============================================================================
# PREVIEW HOSTING
# =============================================================================

def start_preview(
    codebundle: CodeBundle,
    plan: Optional[Plan] = None,
    session_id: str = "default",
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> PreviewResult:
    """
    Start a preview container for a web application.
    
    Args:
        codebundle: The generated code bundle
        plan: Optional plan with language/framework info
        session_id: Session identifier for tracking
        ttl_minutes: Time-to-live in minutes (default 15)
        
    Returns:
        PreviewResult with URL if successful
    """
    # Check Docker availability
    if not DOCKER_AVAILABLE:
        return PreviewResult(
            status="error",
            message="Docker Python SDK not installed. Run: pip install docker",
        )
    
    # Clean up stale registry entries
    cleanup_stale_entries()
    
    # Check if there's already a running preview for this session
    existing = get_session_container(session_id)
    if existing and existing.status == "running":
        return PreviewResult(
            status="already_running",
            url=existing.url,
            container_id=existing.container_id,
            port=existing.port,
            time_remaining=existing.time_remaining_formatted(),
            message="Preview already running. Stop it first to start a new one.",
            language=existing.language,
            framework=existing.framework,
        )
    
    # Detect language
    language = plan.language if plan else None
    if not language:
        # Try to detect from files
        files = codebundle.files
        if any(f.endswith('.py') for f in files):
            language = "Python"
        elif "package.json" in files or any(f.endswith('.js') for f in files):
            language = "JavaScript"
        else:
            return PreviewResult(
                status="unsupported",
                message="Could not detect language. Only Python and Node.js are supported.",
            )
    
    # Detect framework
    framework = detect_framework(codebundle, plan)
    if not framework:
        return PreviewResult(
            status="unsupported",
            message="No web framework detected. Preview hosting requires a web application (FastAPI, Flask, Express, etc.).",
            language=language,
        )
    
    # Get Docker image
    docker_image = DOCKER_IMAGES.get(language)
    if not docker_image:
        return PreviewResult(
            status="unsupported",
            message=f"No Docker image configured for {language}.",
            language=language,
        )
    
    # Allocate port
    port = allocate_port()
    if not port:
        return PreviewResult(
            status="error",
            message="No available ports. Too many preview containers running.",
            language=language,
            framework=framework,
        )
    
    # Get internal port
    internal_port = get_internal_port(framework)
    
    # Create temp directory
    temp_dir = None
    container = None
    
    try:
        # Create Docker client
        client = docker.from_env()
        client.ping()
        
        # Create temp directory with code
        temp_dir = tempfile.mkdtemp(prefix="preview_")
        
        # Write files
        files = codebundle.files
        for file_path, content in files.items():
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # Pull image if needed
        try:
            client.images.get(docker_image)
        except ImageNotFound:
            client.images.pull(docker_image)
        
        # Build commands
        install_cmd = _build_install_command(files, language, framework)
        run_cmd = _build_run_command(files, language, framework)
        
        # Build full command
        if install_cmd:
            full_cmd = f"{install_cmd} && {run_cmd}"
        else:
            full_cmd = run_cmd
        
        # Generate container name
        container_name = f"preview_{session_id[:8]}_{port}"
        
        # Clean up any existing container with the same name
        _cleanup_old_containers(client, container_name)
        
        # Determine memory limit based on language/framework
        # Node.js apps (especially React/Vue) need more memory for webpack
        framework_lower = framework.lower() if framework else ""
        if language in ("JavaScript", "javascript", "Node.js", "node.js", "nodejs", "TypeScript", "typescript"):
            mem_limit = MAX_MEMORY_NODEJS
        else:
            mem_limit = MAX_MEMORY_PYTHON
        
        # Build environment variables
        env_vars = {
            "HOST": "0.0.0.0",
            "PORT": str(internal_port),
        }
        
        # Add framework-specific environment variables
        if framework_lower in ("react", "next", "next.js", "nextjs"):
            # Create React App and Next.js specific
            env_vars.update({
                "BROWSER": "none",           # Don't try to open browser
                "CI": "true",                # Non-interactive mode
                "CHOKIDAR_USEPOLLING": "true",  # File watching in Docker
                "WATCHPACK_POLLING": "true",    # Webpack 5 polling
            })
        elif framework_lower in ("vue", "angular", "nuxt"):
            env_vars.update({
                "BROWSER": "none",
                "CI": "true",
                "CHOKIDAR_USEPOLLING": "true",
            })
        
        # Start container with port exposed
        container = client.containers.run(
            image=docker_image,
            command=["sh", "-c", full_cmd],
            working_dir="/app",
            volumes={temp_dir: {"bind": "/app", "mode": "rw"}},
            ports={f"{internal_port}/tcp": port},
            mem_limit=mem_limit,
            cpu_period=100000,
            cpu_quota=int(100000 * MAX_CPU),
            network_disabled=False,  # Network enabled for web apps
            detach=True,
            remove=False,
            name=container_name,
            environment=env_vars,
        )
        
        # Brief wait to ensure container starts
        time.sleep(3)
        
        # Check if container crashed immediately
        container.reload()
        if container.status != "running":
            logs = container.logs().decode('utf-8', errors='replace')
            container.remove(force=True)
            return PreviewResult(
                status="error",
                message=f"Container failed to start. Logs:\n{logs[:500]}",
                language=language,
                framework=framework,
            )
        
        # Build URL
        url = f"http://localhost:{port}"
        
        # Get initial logs
        initial_logs = container.logs().decode('utf-8', errors='replace')
        
        # Register container with "starting" status
        preview_container = PreviewContainer(
            container_id=container.id,
            container_name=container_name,
            port=port,
            internal_port=internal_port,
            start_time=datetime.now().isoformat(),
            ttl_minutes=ttl_minutes,
            session_id=session_id,
            language=language,
            framework=framework,
            url=url,
            status="starting",  # Not "running" yet - app may still be installing deps
        )
        register_container(preview_container)
        
        # Check if app is already ready (fast Python apps)
        is_ready = _check_port_quick(port)
        
        if is_ready:
            # Update status to running
            get_registry().update_status(container.id, "running")
            return PreviewResult(
                status="running",
                url=url,
                container_id=container.id,
                port=port,
                time_remaining=f"{ttl_minutes}m 0s",
                message=f"✅ Preview ready! Your {framework} app is running.",
                language=language,
                framework=framework,
                logs=initial_logs[-1000:] if initial_logs else None,
                ready=True,
            )
        else:
            # App is still starting (probably installing deps)
            # Create appropriate message based on framework
            if framework_lower in SLOW_INSTALL_FRAMEWORKS:
                startup_message = (
                    f"🔄 Container started. Installing {framework} dependencies...\n\n"
                    f"⏳ **This typically takes 3-5 minutes** for React/Vue/Angular apps.\n\n"
                    f"Keep clicking 'Check Status' to see when it's ready."
                )
            else:
                startup_message = f"🔄 Container started. Installing dependencies..."
            
            return PreviewResult(
                status="starting",
                url=url,
                container_id=container.id,
                port=port,
                time_remaining=f"{ttl_minutes}m 0s",
                message=startup_message,
                language=language,
                framework=framework,
                logs=initial_logs[-1000:] if initial_logs else None,
                ready=False,
            )
        
    except docker.errors.APIError as e:
        error_msg = str(e)
        if "port is already allocated" in error_msg.lower():
            return PreviewResult(
                status="error",
                message=f"Port {port} is already in use. Please try again.",
                language=language,
                framework=framework,
            )
        return PreviewResult(
            status="error",
            message=f"Docker API error: {error_msg[:200]}",
            language=language,
            framework=framework,
        )
        
    except Exception as e:
        # Cleanup on error
        if container:
            try:
                container.stop(timeout=1)
                container.remove(force=True)
            except Exception:
                pass
        
        error_msg = str(e)
        if "connection refused" in error_msg.lower() or "docker daemon" in error_msg.lower():
            return PreviewResult(
                status="error",
                message="Docker is not running. Please start Docker and try again.",
                language=language,
                framework=framework,
            )
        
        return PreviewResult(
            status="error",
            message=f"Failed to start preview: {error_msg[:200]}",
            language=language,
            framework=framework,
        )


def stop_preview(container_id: str) -> PreviewResult:
    """
    Stop a running preview container.
    
    Args:
        container_id: The container ID to stop
        
    Returns:
        PreviewResult indicating success or failure
    """
    from src.sandbox.registry import stop_container
    
    success = stop_container(container_id)
    
    if success:
        return PreviewResult(
            status="stopped",
            message="Preview stopped successfully.",
        )
    else:
        return PreviewResult(
            status="error",
            message="Failed to stop preview. Container may have already stopped.",
        )


def get_preview_status(session_id: str) -> Optional[PreviewResult]:
    """
    Get the status of the current preview for a session.
    Also checks if the app is ready (port responding) and updates status accordingly.
    
    Args:
        session_id: Session identifier
        
    Returns:
        PreviewResult with current status, or None if no preview
    """
    container = get_session_container(session_id)
    
    if not container:
        return None
    
    # Check if expired
    if container.is_expired():
        from src.sandbox.registry import stop_container
        stop_container(container.container_id)
        return PreviewResult(
            status="expired",
            message="Preview has expired and was stopped.",
            container_id=container.container_id,
        )
    
    # Check if container is still actually running
    if DOCKER_AVAILABLE:
        try:
            client = docker.from_env()
            docker_container = client.containers.get(container.container_id)
            docker_container.reload()
            
            if docker_container.status != "running":
                # Container crashed
                logs = docker_container.logs(tail=50).decode('utf-8', errors='replace')
                get_registry().update_status(container.container_id, "error")
                return PreviewResult(
                    status="error",
                    message="Container stopped unexpectedly.",
                    container_id=container.container_id,
                    logs=logs,
                    ready=False,
                )
            
            # Get latest logs
            logs = docker_container.logs(tail=50).decode('utf-8', errors='replace')
            
            # Check if app is ready (port responding)
            is_ready = _check_port_quick(container.port)
            
            if is_ready and container.status == "starting":
                # App is now ready! Update status
                get_registry().update_status(container.container_id, "running")
                return PreviewResult(
                    status="running",
                    url=container.url,
                    container_id=container.container_id,
                    port=container.port,
                    time_remaining=container.time_remaining_formatted(),
                    language=container.language,
                    framework=container.framework,
                    message="✅ App is ready! Click the URL to open.",
                    logs=logs,
                    ready=True,
                )
            elif is_ready:
                return PreviewResult(
                    status="running",
                    url=container.url,
                    container_id=container.container_id,
                    port=container.port,
                    time_remaining=container.time_remaining_formatted(),
                    language=container.language,
                    framework=container.framework,
                    logs=logs,
                    ready=True,
                )
            else:
                # Still starting
                return PreviewResult(
                    status="starting",
                    url=container.url,
                    container_id=container.container_id,
                    port=container.port,
                    time_remaining=container.time_remaining_formatted(),
                    language=container.language,
                    framework=container.framework,
                    message="🔄 Still starting... Dependencies may be installing.",
                    logs=logs,
                    ready=False,
                )
                
        except docker.errors.NotFound:
            # Container no longer exists
            get_registry().update_status(container.container_id, "stopped")
            return PreviewResult(
                status="stopped",
                message="Container no longer exists.",
                container_id=container.container_id,
            )
        except Exception as e:
            pass
    
    # Fallback if Docker check fails
    return PreviewResult(
        status=container.status,
        url=container.url,
        container_id=container.container_id,
        port=container.port,
        time_remaining=container.time_remaining_formatted(),
        language=container.language,
        framework=container.framework,
        ready=container.status == "running",
    )


def get_container_logs(container_id: str, tail: int = 100) -> str:
    """
    Get logs from a running preview container.
    
    Args:
        container_id: The container ID
        tail: Number of lines to return
        
    Returns:
        Log output as string
    """
    if not DOCKER_AVAILABLE:
        return "Docker not available"
    
    try:
        client = docker.from_env()
        container = client.containers.get(container_id)
        logs = container.logs(tail=tail).decode('utf-8', errors='replace')
        return logs
    except Exception as e:
        return f"Error getting logs: {str(e)}"

