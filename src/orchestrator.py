"""
Orchestrator for the code generation pipeline.
"""

from pathlib import Path
from typing import Optional

from src.schemas import Plan, CodeBundle, GenerationResult, PlanFile
from src.llm.azure_openai_client import get_azure_client, JSONParseError


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = Path(__file__).parent / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8")


def generate_plan(
    user_query: str,
    language_pref: str,
    framework_pref: Optional[str],
    executable: bool,
) -> Plan:
    """
    Generate a project plan from the user's query.
    
    Args:
        user_query: The user's description of what they want to build
        language_pref: Preferred programming language ("Auto" for automatic selection)
        framework_pref: Optional preferred framework
        executable: Whether the project should be executable
        
    Returns:
        A validated Plan object
        
    Raises:
        JSONParseError: If the LLM response cannot be parsed
        ValidationError: If the parsed JSON doesn't match the Plan schema
    """
    client = get_azure_client()
    system_prompt = _load_prompt("plan_system.txt")
    
    # Build user prompt with preferences
    user_prompt_parts = [
        f"User Request: {user_query}",
        "",
        "Preferences:",
    ]
    
    if language_pref != "Auto":
        user_prompt_parts.append(f"- Language: {language_pref}")
    else:
        user_prompt_parts.append("- Language: Choose the most appropriate language for this task")
    
    if framework_pref:
        user_prompt_parts.append(f"- Framework: {framework_pref}")
    else:
        user_prompt_parts.append("- Framework: Choose if appropriate, or use none")
    
    user_prompt_parts.append(f"- Should be executable: {executable}")
    
    user_prompt = "\n".join(user_prompt_parts)
    
    # Call LLM
    response_dict = client.invoke_json(system_prompt, user_prompt)
    
    # Validate against schema
    plan = Plan.model_validate(response_dict)
    
    return plan


def generate_code(
    user_query: str,
    plan: Plan,
) -> CodeBundle:
    """
    Generate code files based on the plan.
    
    Args:
        user_query: The original user query
        plan: The validated project plan
        
    Returns:
        A CodeBundle containing all generated files
        
    Raises:
        JSONParseError: If the LLM response cannot be parsed
        ValidationError: If the parsed JSON doesn't match the CodeBundle schema
    """
    client = get_azure_client()
    system_prompt = _load_prompt("code_system.txt")
    
    # Build user prompt with plan details
    user_prompt_parts = [
        "## Original User Request",
        user_query,
        "",
        "## Project Plan",
        f"Language: {plan.language}",
        f"Framework: {plan.framework or 'None'}",
        f"Executable: {plan.executable}",
        "",
        "### Summary",
        plan.summary,
        "",
        "### Files to Generate",
    ]
    
    for f in plan.files:
        user_prompt_parts.append(f"- {f.path}: {f.purpose}")
    
    user_prompt_parts.extend([
        "",
        "### Dependencies",
    ])
    
    for dep in plan.dependencies:
        user_prompt_parts.append(f"- {dep}")
    
    user_prompt_parts.extend([
        "",
        "### Run Steps",
    ])
    
    for i, step in enumerate(plan.steps, 1):
        user_prompt_parts.append(f"{i}. {step}")
    
    user_prompt_parts.extend([
        "",
        "Now generate all the code files. Remember to return STRICT JSON only.",
    ])
    
    user_prompt = "\n".join(user_prompt_parts)
    
    # Call LLM
    response_dict = client.invoke_json(system_prompt, user_prompt)
    
    # Validate against schema
    code_bundle = CodeBundle.model_validate(response_dict)
    
    # Ensure essential files are present
    code_bundle = _ensure_essential_files(code_bundle, plan)
    
    return code_bundle


def _ensure_essential_files(code_bundle: CodeBundle, plan: Plan) -> CodeBundle:
    """Ensure README.md and .gitignore are present in the code bundle."""
    files = dict(code_bundle.files)
    
    # Check for README.md (case-insensitive)
    has_readme = any(f.lower() == "readme.md" for f in files.keys())
    if not has_readme:
        files["README.md"] = _generate_default_readme(plan)
    
    # Check for .gitignore
    if ".gitignore" not in files:
        files[".gitignore"] = _generate_default_gitignore(plan.language)
    
    return CodeBundle(files=files, notes=code_bundle.notes)


def _generate_default_readme(plan: Plan) -> str:
    """Generate a default README.md if the LLM didn't provide one."""
    lines = [
        f"# {plan.summary.split('.')[0]}",
        "",
        plan.summary,
        "",
        "## Technology",
        "",
        f"- Language: {plan.language}",
    ]
    
    if plan.framework:
        lines.append(f"- Framework: {plan.framework}")
    
    if plan.dependencies:
        lines.extend([
            "",
            "## Dependencies",
            "",
        ])
        for dep in plan.dependencies:
            lines.append(f"- {dep}")
    
    if plan.steps:
        lines.extend([
            "",
            "## How to Run",
            "",
        ])
        for i, step in enumerate(plan.steps, 1):
            lines.append(f"{i}. `{step}`")
    
    lines.append("")
    return "\n".join(lines)


def _generate_default_gitignore(language: str) -> str:
    """Generate a default .gitignore based on language."""
    common = [
        "# IDE",
        ".idea/",
        ".vscode/",
        "*.swp",
        "*.swo",
        ".DS_Store",
        "",
    ]
    
    language_specific = {
        "Python": [
            "# Python",
            "__pycache__/",
            "*.py[cod]",
            "*$py.class",
            ".env",
            ".venv/",
            "venv/",
            "env/",
            "*.egg-info/",
            "dist/",
            "build/",
        ],
        "JavaScript": [
            "# Node.js",
            "node_modules/",
            "npm-debug.log",
            ".env",
            "dist/",
            "build/",
        ],
        "TypeScript": [
            "# Node.js / TypeScript",
            "node_modules/",
            "npm-debug.log",
            ".env",
            "dist/",
            "build/",
            "*.js",
            "*.d.ts",
            "*.js.map",
        ],
        "Go": [
            "# Go",
            "*.exe",
            "*.exe~",
            "*.dll",
            "*.so",
            "*.dylib",
            "*.test",
            "*.out",
            "vendor/",
        ],
        "Java": [
            "# Java",
            "*.class",
            "*.jar",
            "*.war",
            "*.ear",
            "target/",
            ".gradle/",
            "build/",
        ],
        "Rust": [
            "# Rust",
            "target/",
            "Cargo.lock",
            "**/*.rs.bk",
        ],
        "C#": [
            "# C#",
            "bin/",
            "obj/",
            "*.dll",
            "*.exe",
            "*.pdb",
            ".vs/",
        ],
    }
    
    specific = language_specific.get(language, language_specific["Python"])
    
    return "\n".join(common + specific + [""])


def generate_project(
    user_query: str,
    language_pref: str,
    framework_pref: Optional[str],
    executable: bool,
) -> GenerationResult:
    """
    Generate a complete project from a user query.
    
    This is the main entry point for the generation pipeline.
    
    Args:
        user_query: The user's description of what they want to build
        language_pref: Preferred programming language ("Auto" for automatic selection)
        framework_pref: Optional preferred framework
        executable: Whether the project should be executable
        
    Returns:
        A GenerationResult containing both the plan and generated code
    """
    # Step 1: Generate plan
    plan = generate_plan(user_query, language_pref, framework_pref, executable)
    
    # Step 2: Generate code based on plan
    code = generate_code(user_query, plan)
    
    return GenerationResult(plan=plan, code=code)

