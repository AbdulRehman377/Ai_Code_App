"""
Pydantic schemas for structured LLM outputs.
"""

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    """A single turn in a conversation."""
    role: Literal["user", "assistant"] = Field(..., description="Role of the speaker")
    content: str = Field(..., description="Message content")


class IntentResult(BaseModel):
    """Result of intent classification."""
    intent: Literal["chat", "build", "regen_file"] = Field(
        ..., 
        description="Classified intent: chat, build, or regen_file"
    )
    reason: str = Field(..., description="Explanation for the classification")


class PlanFile(BaseModel):
    """A file to be generated in the project."""
    path: str = Field(..., description="File path relative to project root")
    purpose: str = Field(..., description="Brief description of the file's purpose")


class Plan(BaseModel):
    """Project plan generated from user query."""
    language: str = Field(..., description="Primary programming language")
    framework: Optional[str] = Field(None, description="Framework to use, if any")
    executable: bool = Field(True, description="Whether the project should be executable")
    sandbox_required: bool = Field(False, description="Whether sandboxing is required")
    summary: str = Field(..., description="Brief summary of the project")
    files: List[PlanFile] = Field(..., description="List of files to generate")
    steps: List[str] = Field(..., description="Steps to run the project")
    dependencies: List[str] = Field(..., description="Required dependencies")


class CodeBundle(BaseModel):
    """Bundle of generated code files."""
    files: Dict[str, str] = Field(..., description="Map of file path to file content")
    notes: Optional[str] = Field(None, description="Additional notes about the generated code")


class GenerationResult(BaseModel):
    """Complete result of the generation process."""
    plan: Plan
    code: CodeBundle


class SessionMemory(BaseModel):
    """
    Session memory structure for Streamlit state.
    This is used to track conversation context and build state.
    """
    chat_history: List[ChatTurn] = Field(default_factory=list, description="Conversation history")
    last_plan: Optional[Plan] = Field(None, description="Last generated plan")
    last_codebundle: Optional[CodeBundle] = Field(None, description="Last generated code bundle")
    last_build_query: Optional[str] = Field(None, description="Last build query from user")
    last_prefs: Optional[Dict[str, str]] = Field(None, description="Last build preferences")
    last_intent: Optional[str] = Field(None, description="Last classified intent")
    errors: List[str] = Field(default_factory=list, description="List of errors encountered")


class ExecutionResult(BaseModel):
    """Result of sandbox code execution."""
    status: Literal["success", "error", "timeout", "skipped"] = Field(
        ..., description="Execution status"
    )
    stdout: str = Field(default="", description="Standard output from execution")
    stderr: str = Field(default="", description="Standard error from execution")
    exit_code: Optional[int] = Field(None, description="Process exit code")
    message: Optional[str] = Field(None, description="Additional status message")
    language: Optional[str] = Field(None, description="Language that was executed")

