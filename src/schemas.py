"""
Pydantic schemas for structured LLM outputs.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


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

