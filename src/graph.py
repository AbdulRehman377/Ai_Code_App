"""
LangGraph implementation for the AI Code Generator.

Implements a minimal state graph with nodes:
- intent_router: Classifies user intent
- chat_node: Handles conversational responses
- plan_node: Generates project plans
- code_node: Generates code files
- regen_file_node: Regenerates a single file
"""

from pathlib import Path
from typing import Literal

from langgraph.graph import StateGraph, END

from src.state import GraphState
from src.schemas import Plan, CodeBundle, IntentResult, ChatTurn, GenerationResult
from src.llm.azure_openai_client import get_azure_client, JSONParseError


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = Path(__file__).parent / "prompts" / filename
    return prompt_path.read_text(encoding="utf-8")


def _get_recent_history_text(chat_history: list, max_turns: int = 6) -> str:
    """Get a text summary of recent chat history."""
    if not chat_history:
        return "No previous conversation."
    
    recent = chat_history[-max_turns:]
    lines = []
    for turn in recent:
        role = turn.get("role", "user") if isinstance(turn, dict) else turn.role
        content = turn.get("content", "") if isinstance(turn, dict) else turn.content
        lines.append(f"{role.upper()}: {content[:200]}...")
    
    return "\n".join(lines)


def _get_plan_summary(plan: Plan) -> str:
    """Get a brief summary of the plan."""
    if not plan:
        return "No existing project."
    
    files = ", ".join([f.path for f in plan.files[:5]])
    return f"Project: {plan.summary}\nLanguage: {plan.language}, Framework: {plan.framework or 'None'}\nFiles: {files}"


# =============================================================================
# GRAPH NODES
# =============================================================================

def intent_router(state: GraphState) -> GraphState:
    """
    Classify the user's intent.
    
    Routes to: chat_node, plan_node, or regen_file_node
    """
    client = get_azure_client()
    system_prompt = _load_prompt("intent_system.txt")
    
    # Build context
    has_project = state.get("codebundle") is not None
    recent_context = _get_recent_history_text(state.get("chat_history", []))
    
    user_prompt = f"""User message: {state["user_input"]}

Context:
- has_existing_project: {has_project}
- recent_context: {recent_context}

Classify the intent."""

    try:
        response = client.invoke_json(system_prompt, user_prompt)
        intent_result = IntentResult.model_validate(response)
        
        state["intent"] = intent_result.intent
        state["intent_reason"] = intent_result.reason
        
    except (JSONParseError, Exception) as e:
        # Default to chat on error
        state["intent"] = "chat"
        state["intent_reason"] = f"Defaulted to chat due to error: {str(e)}"
        state["errors"] = state.get("errors", []) + [str(e)]
    
    return state


def chat_node(state: GraphState) -> GraphState:
    """
    Handle conversational responses.
    """
    client = get_azure_client()
    system_prompt = _load_prompt("chat_system.txt")
    
    # Build context-aware prompt
    context_parts = [system_prompt]
    
    # Add project context if available
    if state.get("plan"):
        context_parts.append(f"\nCurrent project context:\n{_get_plan_summary(state['plan'])}")
    
    full_system = "\n".join(context_parts)
    
    # Get recent chat history for context
    chat_history = state.get("chat_history", [])
    history_for_llm = []
    for turn in chat_history[-12:]:  # Last 12 turns
        if isinstance(turn, dict):
            history_for_llm.append(turn)
        else:
            history_for_llm.append({"role": turn.role, "content": turn.content})
    
    try:
        response = client.invoke_text(
            full_system,
            state["user_input"],
            chat_history=history_for_llm
        )
        
        state["final_chat_response"] = response
        
        # Update chat history
        new_history = list(chat_history)
        new_history.append(ChatTurn(role="user", content=state["user_input"]))
        new_history.append(ChatTurn(role="assistant", content=response))
        state["chat_history"] = new_history
        
    except Exception as e:
        state["final_chat_response"] = f"I encountered an error: {str(e)}"
        state["errors"] = state.get("errors", []) + [str(e)]
    
    return state


def plan_node(state: GraphState) -> GraphState:
    """
    Generate a project plan from the user's query.
    """
    client = get_azure_client()
    system_prompt = _load_prompt("plan_system.txt")
    
    # Build user prompt with preferences
    user_prompt_parts = [
        f"User Request: {state['user_input']}",
        "",
        "Preferences:",
    ]
    
    language_pref = state.get("language_pref", "Auto")
    if language_pref != "Auto":
        user_prompt_parts.append(f"- Language: {language_pref}")
    else:
        user_prompt_parts.append("- Language: Choose the most appropriate language for this task")
    
    framework_pref = state.get("framework_pref")
    if framework_pref:
        user_prompt_parts.append(f"- Framework: {framework_pref}")
    else:
        user_prompt_parts.append("- Framework: Choose if appropriate, or use none")
    
    executable = state.get("executable", True)
    user_prompt_parts.append(f"- Should be executable: {executable}")
    
    user_prompt = "\n".join(user_prompt_parts)
    
    try:
        response = client.invoke_json(system_prompt, user_prompt)
        plan = Plan.model_validate(response)
        state["plan"] = plan
        
    except (JSONParseError, Exception) as e:
        state["errors"] = state.get("errors", []) + [f"Plan generation failed: {str(e)}"]
    
    return state


def code_node(state: GraphState) -> GraphState:
    """
    Generate code files based on the plan.
    """
    plan = state.get("plan")
    if not plan:
        state["errors"] = state.get("errors", []) + ["No plan available for code generation"]
        return state
    
    client = get_azure_client()
    system_prompt = _load_prompt("code_system.txt")
    
    # Build user prompt with plan details
    user_prompt_parts = [
        "## Original User Request",
        state["user_input"],
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
    
    user_prompt = "\n".join(user_prompt_parts)
    
    try:
        response = client.invoke_json(system_prompt, user_prompt)
        code_bundle = CodeBundle.model_validate(response)
        
        # Ensure essential files
        code_bundle = _ensure_essential_files(code_bundle, plan)
        
        state["codebundle"] = code_bundle
        
        # Build final result
        state["final_result"] = GenerationResult(plan=plan, code=code_bundle).model_dump()
        
        # Update chat history with build context
        chat_history = list(state.get("chat_history", []))
        chat_history.append(ChatTurn(role="user", content=state["user_input"]))
        chat_history.append(ChatTurn(
            role="assistant", 
            content=f"I've generated a {plan.language} project: {plan.summary}. It includes {len(code_bundle.files)} files."
        ))
        state["chat_history"] = chat_history
        
    except (JSONParseError, Exception) as e:
        state["errors"] = state.get("errors", []) + [f"Code generation failed: {str(e)}"]
    
    return state


def regen_file_node(state: GraphState) -> GraphState:
    """
    Regenerate a single file based on user instructions.
    """
    plan = state.get("plan")
    codebundle = state.get("codebundle")
    regen_path = state.get("regen_file_path")
    regen_instructions = state.get("regen_instructions")
    
    if not all([plan, codebundle, regen_path, regen_instructions]):
        state["errors"] = state.get("errors", []) + [
            "Missing required data for file regeneration. Need: plan, codebundle, file path, and instructions."
        ]
        return state
    
    current_content = codebundle.files.get(regen_path)
    if current_content is None:
        state["errors"] = state.get("errors", []) + [f"File '{regen_path}' not found in code bundle."]
        return state
    
    client = get_azure_client()
    system_prompt = _load_prompt("regen_file_system.txt")
    
    # Build user prompt
    user_prompt = f"""## Project Plan
Language: {plan.language}
Framework: {plan.framework or 'None'}
Summary: {plan.summary}

## File to Regenerate
Path: {regen_path}

## Current Content
```
{current_content}
```

## User Instructions
{regen_instructions}

Generate the updated file content. Remember to output ONLY the JSON with the single file."""

    try:
        response = client.invoke_json(system_prompt, user_prompt)
        
        # Validate response has the expected file
        new_files = response.get("files", {})
        if regen_path not in new_files:
            # Try to find any file in response
            if len(new_files) == 1:
                # Use the single file returned, map to our path
                new_content = list(new_files.values())[0]
            else:
                raise ValueError(f"Response did not contain the expected file: {regen_path}")
        else:
            new_content = new_files[regen_path]
        
        # Update the codebundle
        updated_files = dict(codebundle.files)
        updated_files[regen_path] = new_content
        
        new_codebundle = CodeBundle(
            files=updated_files,
            notes=response.get("notes") or codebundle.notes
        )
        
        state["codebundle"] = new_codebundle
        state["final_result"] = GenerationResult(plan=plan, code=new_codebundle).model_dump()
        
        # Update chat history
        chat_history = list(state.get("chat_history", []))
        chat_history.append(ChatTurn(role="user", content=f"Regenerate {regen_path}: {regen_instructions}"))
        chat_history.append(ChatTurn(role="assistant", content=f"I've regenerated the file '{regen_path}' based on your instructions."))
        state["chat_history"] = chat_history
        
    except (JSONParseError, Exception) as e:
        state["errors"] = state.get("errors", []) + [f"File regeneration failed: {str(e)}"]
    
    return state


def _normalize_and_deduplicate_files(files: dict) -> dict:
    """
    Normalize file names and remove duplicates.
    
    Handles common LLM mistakes like:
    - 'gitignore' instead of '.gitignore'
    - 'README' instead of 'README.md'
    - Case variations like 'readme.md' vs 'README.md'
    - Duplicate files with slight name variations
    """
    normalized = {}
    
    # Define canonical names for common files
    # Maps variations to the correct canonical name
    canonical_names = {
        # .gitignore variations
        "gitignore": ".gitignore",
        ".gitignore": ".gitignore",
        "git-ignore": ".gitignore",
        "git_ignore": ".gitignore",
        # README variations
        "readme": "README.md",
        "readme.md": "README.md",
        "readme.txt": "README.md",
        "read-me.md": "README.md",
        # package.json variations
        "package.json": "package.json",
        "packagejson": "package.json",
        # requirements.txt variations
        "requirements.txt": "requirements.txt",
        "requirements": "requirements.txt",
        # vite.config variations
        "vite.config.js": "vite.config.js",
        "viteconfig.js": "vite.config.js",
        "vite.config.ts": "vite.config.ts",
    }
    
    # Track which canonical files we've already added
    seen_canonical = set()
    
    for file_path, content in files.items():
        # Get the filename (last part of path)
        parts = file_path.replace("\\", "/").split("/")
        filename = parts[-1]
        dir_path = "/".join(parts[:-1])
        
        # Check if this is a known file that needs normalization
        filename_lower = filename.lower()
        
        # Look up canonical name
        canonical = canonical_names.get(filename_lower)
        
        if canonical:
            # This is a known file - use canonical name
            if dir_path:
                full_canonical = f"{dir_path}/{canonical}"
            else:
                full_canonical = canonical
            
            # Only add if we haven't seen this canonical file yet
            if full_canonical.lower() not in seen_canonical:
                normalized[full_canonical] = content
                seen_canonical.add(full_canonical.lower())
            # If we've already seen it, skip (keep the first one)
        else:
            # Not a known file - check for exact duplicates (case-insensitive)
            if file_path.lower() not in seen_canonical:
                normalized[file_path] = content
                seen_canonical.add(file_path.lower())
    
    return normalized


def _ensure_essential_files(code_bundle: CodeBundle, plan: Plan) -> CodeBundle:
    """Ensure README.md and .gitignore are present in the code bundle."""
    # First, normalize and deduplicate files
    files = _normalize_and_deduplicate_files(dict(code_bundle.files))
    
    # Check for README.md (case-insensitive)
    has_readme = any(f.lower() == "readme.md" for f in files.keys())
    if not has_readme:
        files["README.md"] = _generate_default_readme(plan)
    
    # Check for .gitignore (already normalized, so exact match is fine)
    has_gitignore = any(f.lower() == ".gitignore" for f in files.keys())
    if not has_gitignore:
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


# =============================================================================
# ROUTING LOGIC
# =============================================================================

def route_by_intent(state: GraphState) -> Literal["chat_node", "plan_node", "regen_file_node"]:
    """Route to the appropriate node based on intent."""
    intent = state.get("intent", "chat")
    
    if intent == "build":
        return "plan_node"
    elif intent == "regen_file":
        # Check if we have what we need for regen
        if state.get("codebundle") and state.get("regen_file_path"):
            return "regen_file_node"
        else:
            # Fall back to plan if no project exists
            return "plan_node"
    else:
        return "chat_node"


def after_plan_route(state: GraphState) -> Literal["code_node", "end"]:
    """After planning, route to code generation or end on error."""
    if state.get("plan"):
        return "code_node"
    return "end"


# =============================================================================
# BUILD THE GRAPH
# =============================================================================

def build_graph() -> StateGraph:
    """Build and return the LangGraph state graph."""
    
    # Create the graph
    graph = StateGraph(GraphState)
    
    # Add nodes
    graph.add_node("intent_router", intent_router)
    graph.add_node("chat_node", chat_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("code_node", code_node)
    graph.add_node("regen_file_node", regen_file_node)
    
    # Set entry point
    graph.set_entry_point("intent_router")
    
    # Add conditional edges from intent_router
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "chat_node": "chat_node",
            "plan_node": "plan_node",
            "regen_file_node": "regen_file_node",
        }
    )
    
    # Add conditional edges from plan_node
    graph.add_conditional_edges(
        "plan_node",
        after_plan_route,
        {
            "code_node": "code_node",
            "end": END,
        }
    )
    
    # Terminal edges
    graph.add_edge("chat_node", END)
    graph.add_edge("code_node", END)
    graph.add_edge("regen_file_node", END)
    
    return graph


def get_compiled_graph():
    """Get the compiled graph ready for execution."""
    graph = build_graph()
    return graph.compile()


# Global compiled graph instance
_compiled_graph = None


def get_graph():
    """Get or create the global compiled graph instance."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = get_compiled_graph()
    return _compiled_graph
