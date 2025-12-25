"""
Orchestrator for the code generation pipeline.

Provides wrapper functions for the LangGraph-based workflow.
"""

from typing import Dict, List, Optional, Any

from src.schemas import Plan, CodeBundle, ChatTurn
from src.state import GraphState, create_initial_state
from src.graph import get_graph


# =============================================================================
# GRAPH-BASED ORCHESTRATION
# =============================================================================

def run_graph(
    user_input: str,
    language_pref: str = "Auto",
    framework_pref: Optional[str] = None,
    executable: bool = True,
    chat_history: Optional[List[ChatTurn]] = None,
    existing_plan: Optional[Plan] = None,
    existing_codebundle: Optional[CodeBundle] = None,
    regen_file_path: Optional[str] = None,
    regen_instructions: Optional[str] = None,
    force_intent: Optional[str] = None,
) -> GraphState:
    """
    Run the LangGraph workflow with the given inputs.
    
    This is the main entry point for the graph-based orchestration.
    
    Args:
        user_input: The user's input message
        language_pref: Preferred programming language
        framework_pref: Optional preferred framework
        executable: Whether to generate an executable project
        chat_history: Previous conversation history
        existing_plan: Existing plan (for regeneration)
        existing_codebundle: Existing code bundle (for regeneration)
        regen_file_path: Path of file to regenerate
        regen_instructions: Instructions for regeneration
        force_intent: Force a specific intent (skip intent router)
        
    Returns:
        The final GraphState with results
    """
    # Create initial state
    initial_state = create_initial_state(
        user_input=user_input,
        language_pref=language_pref,
        framework_pref=framework_pref,
        executable=executable,
        chat_history=chat_history,
        plan=existing_plan,
        codebundle=existing_codebundle,
        regen_file_path=regen_file_path,
        regen_instructions=regen_instructions,
    )
    
    # If forcing intent, set it directly
    if force_intent:
        initial_state["intent"] = force_intent
    
    # Get the compiled graph
    graph = get_graph()
    
    # Run the graph
    final_state = graph.invoke(initial_state)
    
    return final_state


def run_chat(
    user_input: str,
    chat_history: Optional[List[ChatTurn]] = None,
    existing_plan: Optional[Plan] = None,
    existing_codebundle: Optional[CodeBundle] = None,
) -> Dict[str, Any]:
    """
    Run a chat interaction.
    
    Args:
        user_input: The user's message
        chat_history: Previous conversation
        existing_plan: Current plan context
        existing_codebundle: Current code context
        
    Returns:
        Dict with 'response' and 'chat_history'
    """
    result = run_graph(
        user_input=user_input,
        chat_history=chat_history,
        existing_plan=existing_plan,
        existing_codebundle=existing_codebundle,
        force_intent="chat",
    )
    
    return {
        "response": result.get("final_chat_response", ""),
        "chat_history": result.get("chat_history", []),
        "errors": result.get("errors", []),
    }


def run_build(
    user_input: str,
    language_pref: str = "Auto",
    framework_pref: Optional[str] = None,
    executable: bool = True,
    chat_history: Optional[List[ChatTurn]] = None,
) -> Dict[str, Any]:
    """
    Run a build operation.
    
    Args:
        user_input: The build request
        language_pref: Preferred language
        framework_pref: Preferred framework
        executable: Whether project should be executable
        chat_history: Previous conversation
        
    Returns:
        Dict with 'plan', 'codebundle', 'chat_history', 'errors'
    """
    result = run_graph(
        user_input=user_input,
        language_pref=language_pref,
        framework_pref=framework_pref,
        executable=executable,
        chat_history=chat_history,
        force_intent="build",
    )
    
    return {
        "plan": result.get("plan"),
        "codebundle": result.get("codebundle"),
        "chat_history": result.get("chat_history", []),
        "errors": result.get("errors", []),
    }


def run_regen_file(
    file_path: str,
    instructions: str,
    existing_plan: Plan,
    existing_codebundle: CodeBundle,
    chat_history: Optional[List[ChatTurn]] = None,
) -> Dict[str, Any]:
    """
    Regenerate a single file.
    
    Args:
        file_path: Path of file to regenerate
        instructions: User's regeneration instructions
        existing_plan: The current plan
        existing_codebundle: The current code bundle
        chat_history: Previous conversation
        
    Returns:
        Dict with updated 'codebundle', 'chat_history', 'errors'
    """
    result = run_graph(
        user_input=f"Regenerate {file_path}",
        chat_history=chat_history,
        existing_plan=existing_plan,
        existing_codebundle=existing_codebundle,
        regen_file_path=file_path,
        regen_instructions=instructions,
        force_intent="regen_file",
    )
    
    return {
        "codebundle": result.get("codebundle"),
        "chat_history": result.get("chat_history", []),
        "errors": result.get("errors", []),
    }


def run_auto(
    user_input: str,
    language_pref: str = "Auto",
    framework_pref: Optional[str] = None,
    executable: bool = True,
    chat_history: Optional[List[ChatTurn]] = None,
    existing_plan: Optional[Plan] = None,
    existing_codebundle: Optional[CodeBundle] = None,
) -> Dict[str, Any]:
    """
    Run with automatic intent detection.
    
    Args:
        user_input: The user's message
        language_pref: Preferred language (for builds)
        framework_pref: Preferred framework (for builds)
        executable: Whether builds should be executable
        chat_history: Previous conversation
        existing_plan: Current plan context
        existing_codebundle: Current code context
        
    Returns:
        Dict with 'intent', 'response', 'plan', 'codebundle', 'chat_history', 'errors'
    """
    result = run_graph(
        user_input=user_input,
        language_pref=language_pref,
        framework_pref=framework_pref,
        executable=executable,
        chat_history=chat_history,
        existing_plan=existing_plan,
        existing_codebundle=existing_codebundle,
    )
    
    return {
        "intent": result.get("intent"),
        "intent_reason": result.get("intent_reason"),
        "response": result.get("final_chat_response"),
        "plan": result.get("plan"),
        "codebundle": result.get("codebundle"),
        "chat_history": result.get("chat_history", []),
        "errors": result.get("errors", []),
    }


