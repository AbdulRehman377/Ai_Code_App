"""
State definitions for LangGraph orchestration.
"""

from typing import Any, Dict, List, Optional, TypedDict
from src.schemas import Plan, CodeBundle, ChatTurn


class GraphState(TypedDict, total=False):
    """
    Typed state dictionary for the LangGraph workflow.
    
    This state is passed between nodes and updated as the graph executes.
    """
    # User input
    user_input: str
    
    # Intent classification
    intent: Optional[str]  # "chat" | "build" | "regen_file"
    intent_reason: Optional[str]
    
    # Build preferences
    language_pref: str
    framework_pref: Optional[str]
    executable: bool
    
    # Conversation history
    chat_history: List[ChatTurn]
    
    # Build artifacts
    plan: Optional[Plan]
    codebundle: Optional[CodeBundle]
    
    # File regeneration
    regen_file_path: Optional[str]
    regen_instructions: Optional[str]
    
    # Outputs
    final_chat_response: Optional[str]
    final_result: Optional[Dict[str, Any]]  # Serialized GenerationResult
    
    # Error tracking
    errors: List[str]


def create_initial_state(
    user_input: str,
    language_pref: str = "Auto",
    framework_pref: Optional[str] = None,
    executable: bool = True,
    chat_history: Optional[List[ChatTurn]] = None,
    plan: Optional[Plan] = None,
    codebundle: Optional[CodeBundle] = None,
    regen_file_path: Optional[str] = None,
    regen_instructions: Optional[str] = None,
) -> GraphState:
    """
    Create an initial state for the graph with provided values.
    
    Args:
        user_input: The user's input text
        language_pref: Preferred programming language
        framework_pref: Optional preferred framework
        executable: Whether to generate executable project
        chat_history: Previous conversation turns
        plan: Existing plan (for regen)
        codebundle: Existing code bundle (for regen)
        regen_file_path: File path to regenerate
        regen_instructions: Instructions for regeneration
        
    Returns:
        Initialized GraphState
    """
    return GraphState(
        user_input=user_input,
        intent=None,
        intent_reason=None,
        language_pref=language_pref,
        framework_pref=framework_pref,
        executable=executable,
        chat_history=chat_history or [],
        plan=plan,
        codebundle=codebundle,
        regen_file_path=regen_file_path,
        regen_instructions=regen_instructions,
        final_chat_response=None,
        final_result=None,
        errors=[],
    )

