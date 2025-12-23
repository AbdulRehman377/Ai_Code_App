"""
Utility functions for the AI Code Generator.
"""

import io
import re
import zipfile
from pathlib import Path
from typing import Dict


def make_zip_bytes(files: Dict[str, str]) -> bytes:
    """
    Create an in-memory ZIP archive from a dictionary of files.
    
    Args:
        files: Dictionary mapping file paths to file contents
        
    Returns:
        Bytes of the ZIP archive
    """
    buffer = io.BytesIO()
    
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            # Normalize path separators
            normalized_path = path.replace("\\", "/")
            # Remove leading slash if present
            if normalized_path.startswith("/"):
                normalized_path = normalized_path[1:]
            zf.writestr(normalized_path, content)
    
    buffer.seek(0)
    return buffer.getvalue()


# Mapping of file extensions to language names for syntax highlighting
EXTENSION_LANGUAGE_MAP = {
    # Python
    ".py": "python",
    ".pyx": "python",
    ".pyi": "python",
    # JavaScript/TypeScript
    ".js": "javascript",
    ".jsx": "jsx",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".mjs": "javascript",
    ".cjs": "javascript",
    # Web
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".less": "less",
    # Data/Config
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    # Shell
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".fish": "fish",
    ".ps1": "powershell",
    ".bat": "batch",
    ".cmd": "batch",
    # Systems
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".cs": "csharp",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    # Other
    ".rb": "ruby",
    ".php": "php",
    ".sql": "sql",
    ".r": "r",
    ".R": "r",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".scala": "scala",
    ".clj": "clojure",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hrl": "erlang",
    ".hs": "haskell",
    ".dart": "dart",
    ".vue": "vue",
    ".svelte": "svelte",
    # Docs/Text
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "rst",
    ".txt": "text",
    # Docker/Build
    "Dockerfile": "dockerfile",
    ".dockerfile": "dockerfile",
    "Makefile": "makefile",
    ".mk": "makefile",
    # Special files
    ".gitignore": "text",
    ".env": "text",
    ".env.example": "text",
    ".editorconfig": "ini",
}

# Special filename mappings (no extension)
FILENAME_LANGUAGE_MAP = {
    "Dockerfile": "dockerfile",
    "Makefile": "makefile",
    "Jenkinsfile": "groovy",
    "Vagrantfile": "ruby",
    "Gemfile": "ruby",
    "Rakefile": "ruby",
    "Procfile": "text",
    ".gitignore": "text",
    ".dockerignore": "text",
    ".env": "text",
    ".env.example": "text",
    ".env.local": "text",
}


def guess_language_from_filename(path: str) -> str:
    """
    Guess the programming language from a filename for syntax highlighting.
    
    Args:
        path: File path or filename
        
    Returns:
        Language name for syntax highlighting, defaults to "text"
    """
    filename = Path(path).name
    
    # Check special filenames first
    if filename in FILENAME_LANGUAGE_MAP:
        return FILENAME_LANGUAGE_MAP[filename]
    
    # Check by extension
    suffix = Path(path).suffix.lower()
    if suffix in EXTENSION_LANGUAGE_MAP:
        return EXTENSION_LANGUAGE_MAP[suffix]
    
    return "text"


def safe_project_name(user_query: str) -> str:
    """
    Generate a safe filename from a user query.
    
    Args:
        user_query: The user's original query
        
    Returns:
        A safe string for use as a project/filename
    """
    # Take first 50 characters
    name = user_query[:50].strip()
    
    # Replace whitespace with underscores
    name = re.sub(r'\s+', '_', name)
    
    # Remove non-alphanumeric characters except underscores and hyphens
    name = re.sub(r'[^\w\-]', '', name)
    
    # Remove leading/trailing underscores
    name = name.strip('_')
    
    # Default if empty
    if not name:
        name = "generated_project"
    
    return name.lower()

