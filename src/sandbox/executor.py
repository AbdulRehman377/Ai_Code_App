"""
Sandbox Executor - Run generated code in isolated Docker containers.

Security Requirements:
- All code runs in fresh Docker containers
- Network disabled during code execution
- Strict resource limits (10s timeout, 512MB memory, 0.5 CPU)
- Containers always cleaned up after execution
- No host filesystem mounts (except temp directory with generated code)

Supported Languages:
- Python (python:3.11-slim)
- Node.js (node:18-alpine)
"""

import os
import shutil
import tempfile
from dataclasses import dataclass
from typing import Dict, Literal, Optional

try:
    import docker  # type: ignore[import-not-found]
    from docker.errors import ContainerError, ImageNotFound, APIError  # type: ignore[import-not-found]
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

from src.schemas import CodeBundle, Plan


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

# Resource limits
MAX_EXECUTION_TIME = 300  # seconds (5 minutes)
MAX_MEMORY = "512m"
MAX_CPU = 0.5

# Supported languages for execution
SUPPORTED_LANGUAGES = {"Python", "python", "JavaScript", "javascript", "Node.js", "node.js", "nodejs", "TypeScript", "typescript"}

# Languages that should NOT be executed (UI frameworks, etc.)
UNSUPPORTED_PATTERNS = ["react", "next", "vue", "angular", "svelte", "gatsby"]


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ExecutionResult:
    """Result of sandbox code execution."""
    status: Literal["success", "error", "timeout", "skipped"]
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    message: Optional[str] = None
    language: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "message": self.message,
            "language": self.language,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ExecutionResult":
        """Create from dictionary."""
        return cls(
            status=data.get("status", "error"),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            exit_code=data.get("exit_code"),
            message=data.get("message"),
            language=data.get("language"),
        )


# =============================================================================
# LANGUAGE DETECTION
# =============================================================================

def detect_language(codebundle: CodeBundle, plan: Optional[Plan] = None) -> Optional[str]:
    """
    Detect the primary language of the code bundle.
    
    Args:
        codebundle: The generated code bundle
        plan: Optional plan with language info
        
    Returns:
        Language name or None if unsupported
    """
    # First, try to get language from plan
    if plan and plan.language:
        lang = plan.language
        if lang in SUPPORTED_LANGUAGES:
            return lang
    
    # Fallback: detect from file extensions
    files = codebundle.files
    
    # Check for Python files
    has_python = any(f.endswith('.py') for f in files.keys())
    
    # Check for JavaScript/Node files
    has_js = any(f.endswith('.js') or f.endswith('.mjs') for f in files.keys())
    has_ts = any(f.endswith('.ts') or f.endswith('.tsx') for f in files.keys())
    
    # Check for package.json to detect Node.js project
    has_package_json = 'package.json' in files
    
    # Check for React/frontend patterns (should skip execution)
    if has_package_json:
        pkg_content = files.get('package.json', '').lower()
        for pattern in UNSUPPORTED_PATTERNS:
            if pattern in pkg_content:
                return None  # Frontend project - skip execution
    
    # Return detected language
    if has_python:
        return "Python"
    elif has_js or has_ts or has_package_json:
        return "JavaScript"
    
    return None


def is_execution_supported(codebundle: CodeBundle, plan: Optional[Plan] = None) -> bool:
    """Check if execution is supported for this code bundle."""
    language = detect_language(codebundle, plan)
    return language is not None


# =============================================================================
# ENTRY FILE DETECTION
# =============================================================================

def find_entry_file(files: Dict[str, str], language: str) -> Optional[str]:
    """
    Find the entry file for execution.
    
    Args:
        files: Dict of file paths to contents
        language: Detected language
        
    Returns:
        Entry file path or None if not found
    """
    file_names = list(files.keys())
    
    if language in ("Python", "python"):
        # Prefer main.py
        if "main.py" in file_names:
            return "main.py"
        # Try app.py
        if "app.py" in file_names:
            return "app.py"
        # Try run.py
        if "run.py" in file_names:
            return "run.py"
        # Return first .py file (excluding tests and __init__)
        for f in file_names:
            if f.endswith('.py') and not f.startswith('test_') and f != '__init__.py':
                return f
    
    elif language in ("JavaScript", "javascript", "Node.js", "node.js", "nodejs", "TypeScript", "typescript"):
        # Check package.json for start script
        if "package.json" in files:
            import json
            try:
                pkg = json.loads(files["package.json"])
                # Check for main field
                main_file = pkg.get("main")
                if main_file and main_file in file_names:
                    return main_file
            except json.JSONDecodeError:
                pass
        
        # Prefer index.js
        if "index.js" in file_names:
            return "index.js"
        # Try main.js
        if "main.js" in file_names:
            return "main.js"
        # Try app.js
        if "app.js" in file_names:
            return "app.js"
        # Try server.js (but mark as potential server)
        if "server.js" in file_names:
            return "server.js"
        # Return first .js file
        for f in file_names:
            if f.endswith('.js') and not f.startswith('test'):
                return f
    
    return None


# =============================================================================
# SANDBOX EXECUTOR
# =============================================================================

def run_sandbox(
    codebundle: CodeBundle,
    plan: Optional[Plan] = None,
) -> ExecutionResult:
    """
    Run generated code in an isolated Docker container.
    
    Lifecycle:
    1. Detect language and entry file
    2. Create temp directory with generated files
    3. Create Docker container with resource limits
    4. Install dependencies (with network)
    5. Run code (without network)
    6. Capture output
    7. Clean up container and temp directory
    
    Args:
        codebundle: The generated code bundle
        plan: Optional plan with language info
        
    Returns:
        ExecutionResult with status, stdout, stderr, exit_code
    """
    # Check if Docker is available
    if not DOCKER_AVAILABLE:
        return ExecutionResult(
            status="skipped",
            message="Docker Python SDK not installed. Run: pip install docker",
        )
    
    # Detect language
    language = detect_language(codebundle, plan)
    if not language:
        return ExecutionResult(
            status="skipped",
            message="Execution not supported yet for this language. Only Python and Node.js are supported.",
            language=plan.language if plan else None,
        )
    
    # Check for React/frontend patterns
    if plan and plan.framework:
        framework_lower = plan.framework.lower()
        for pattern in UNSUPPORTED_PATTERNS:
            if pattern in framework_lower:
                return ExecutionResult(
                    status="skipped",
                    message=f"UI-based applications ({plan.framework}) cannot be previewed. Only console output is captured.",
                    language=language,
                )
    
    # Find entry file
    files = codebundle.files
    entry_file = find_entry_file(files, language)
    if not entry_file:
        return ExecutionResult(
            status="error",
            message=f"No executable entry file found for {language}.",
            language=language,
        )
    
    # Get Docker image
    docker_image = DOCKER_IMAGES.get(language)
    if not docker_image:
        return ExecutionResult(
            status="skipped",
            message=f"No Docker image configured for {language}.",
            language=language,
        )
    
    # Create temp directory and run container
    temp_dir = None
    install_container = None
    run_container = None
    
    try:
        # Create Docker client
        client = docker.from_env()
        
        # Verify Docker is running
        client.ping()
        
        # Create temp directory
        temp_dir = tempfile.mkdtemp(prefix="sandbox_")
        
        # Write files to temp directory
        for file_path, content in files.items():
            # Create subdirectories if needed
            full_path = os.path.join(temp_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            # Write file
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
        
        # Pull image if needed
        try:
            client.images.get(docker_image)
        except ImageNotFound:
            client.images.pull(docker_image)
        
        # Build install command
        install_cmd = _build_install_command(files, language)
        
        # Build run command
        run_cmd = _build_run_command(entry_file, language)
        
        # =========================================================
        # PHASE 1: Install dependencies (network ENABLED)
        # =========================================================
        if install_cmd:
            install_container = client.containers.run(
                image=docker_image,
                command=["sh", "-c", install_cmd],
                working_dir="/app",
                volumes={temp_dir: {"bind": "/app", "mode": "rw"}},  # Read-write for install
                mem_limit=MAX_MEMORY,
                cpu_period=100000,
                cpu_quota=int(100000 * MAX_CPU),
                network_disabled=False,  # Network ENABLED for dependency installation
                detach=True,
                remove=False,
            )
            
            # Wait for installation with extended timeout (60s for deps)
            install_result = install_container.wait(timeout=60)
            install_exit_code = install_result.get("StatusCode", -1)
            
            # Get install logs
            install_stderr = install_container.logs(stdout=False, stderr=True).decode('utf-8', errors='replace')
            
            # Clean up install container
            try:
                install_container.remove(force=True)
            except Exception:
                pass
            install_container = None
            
            # Check if installation failed
            if install_exit_code != 0:
                return ExecutionResult(
                    status="error",
                    stderr=install_stderr,
                    exit_code=install_exit_code,
                    message="Dependency installation failed.",
                    language=language,
                )
        
        # =========================================================
        # PHASE 2: Run code (network DISABLED)
        # =========================================================
        run_container = client.containers.run(
            image=docker_image,
            command=["sh", "-c", run_cmd],
            working_dir="/app",
            volumes={temp_dir: {"bind": "/app", "mode": "ro"}},  # Read-only for execution
            mem_limit=MAX_MEMORY,
            cpu_period=100000,
            cpu_quota=int(100000 * MAX_CPU),
            network_disabled=True,  # Network DISABLED for code execution
            detach=True,
            remove=False,
        )
        
        # Wait for container to finish
        result = run_container.wait(timeout=MAX_EXECUTION_TIME)
        exit_code = result.get("StatusCode", -1)
        
        # Get logs
        stdout = run_container.logs(stdout=True, stderr=False).decode('utf-8', errors='replace')
        stderr = run_container.logs(stdout=False, stderr=True).decode('utf-8', errors='replace')
        
        # Determine status
        if exit_code == 0:
            status = "success"
        else:
            status = "error"
        
        return ExecutionResult(
            status=status,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            language=language,
        )
        
    except docker.errors.ContainerError as e:
        return ExecutionResult(
            status="error",
            stderr=str(e),
            exit_code=e.exit_status if hasattr(e, 'exit_status') else -1,
            message="Container execution failed.",
            language=language,
        )
    
    except Exception as e:
        error_message = str(e)
        
        # Check for timeout
        if "timed out" in error_message.lower() or "timeout" in error_message.lower():
            return ExecutionResult(
                status="timeout",
                message=f"Execution timed out after {MAX_EXECUTION_TIME // 60} minutes.",
                language=language,
            )
        
        # Check for Docker not running
        if "connection refused" in error_message.lower() or "docker daemon" in error_message.lower():
            return ExecutionResult(
                status="error",
                message="Docker is not running. Please start Docker and try again.",
                language=language,
            )
        
        return ExecutionResult(
            status="error",
            stderr=error_message,
            message="Execution failed unexpectedly.",
            language=language,
        )
    
    finally:
        # Always clean up containers
        for container in [install_container, run_container]:
            if container:
                try:
                    container.stop(timeout=1)
                except Exception:
                    pass
                try:
                    container.remove(force=True)
                except Exception:
                    pass
        
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


def _build_install_command(files: Dict[str, str], language: str) -> Optional[str]:
    """Build the dependency installation command if needed."""
    
    if language in ("Python", "python"):
        # First, check for requirements.txt
        if "requirements.txt" in files:
            return "pip install -q -r requirements.txt"
        
        # Otherwise, try to detect imports and install them
        detected_packages = _detect_python_imports(files)
        if detected_packages:
            packages_str = " ".join(detected_packages)
            return f"pip install -q {packages_str}"
    
    elif language in ("JavaScript", "javascript", "Node.js", "node.js", "nodejs", "TypeScript", "typescript"):
        if "package.json" in files:
            return "npm install --silent"
    
    return None


# Common third-party Python packages (stdlib modules excluded)
COMMON_THIRD_PARTY_PACKAGES = {
    # Web frameworks
    "flask", "django", "fastapi", "bottle", "tornado", "starlette",
    # HTTP & APIs
    "requests", "httpx", "aiohttp", "urllib3",
    # Data
    "pandas", "numpy", "scipy", "matplotlib", "seaborn", "plotly",
    # Database
    "sqlalchemy", "pymongo", "redis", "psycopg2", "mysql",
    # Utils
    "click", "typer", "pydantic", "attrs", "dataclasses",
    "pytest", "beautifulsoup4", "bs4", "lxml", "pillow",
    "pyyaml", "toml", "python-dotenv", "cryptography",
    # Async
    "asyncio", "uvicorn", "gunicorn",
}

# Package name mappings (import name -> pip package name)
PACKAGE_NAME_MAP = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "sklearn": "scikit-learn",
}


def _detect_python_imports(files: Dict[str, str]) -> set:
    """
    Detect third-party imports from Python files.
    
    Returns a set of package names to install.
    """
    import re
    
    detected = set()
    
    # Patterns to match import statements
    import_pattern = re.compile(r'^(?:from|import)\s+([a-zA-Z_][a-zA-Z0-9_]*)', re.MULTILINE)
    
    for filename, content in files.items():
        if not filename.endswith('.py'):
            continue
        
        # Find all imports
        matches = import_pattern.findall(content)
        for module in matches:
            # Get the top-level package name
            top_level = module.split('.')[0].lower()
            
            # Check if it's a known third-party package
            if top_level in COMMON_THIRD_PARTY_PACKAGES:
                # Map to correct pip package name if needed
                pip_name = PACKAGE_NAME_MAP.get(top_level, top_level)
                detected.add(pip_name)
    
    return detected



def _build_run_command(entry_file: str, language: str) -> str:
    """Build the execution command for the entry file."""
    
    if language in ("Python", "python"):
        return f"python {entry_file}"
    
    elif language in ("JavaScript", "javascript", "Node.js", "node.js", "nodejs"):
        return f"node {entry_file}"
    
    elif language in ("TypeScript", "typescript"):
        # For TypeScript, we'd need ts-node, but simpler to compile first
        return f"npx ts-node {entry_file}"
    
    return f"echo 'Unknown language: {language}'"
