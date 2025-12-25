"""
Azure OpenAI client with robust JSON parsing and retry logic.
"""

import json
import re
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

from src.config import get_config


class JSONParseError(Exception):
    """Raised when JSON parsing fails even after repair attempts."""
    pass


class AzureOpenAIClient:
    """Client for Azure OpenAI with JSON output enforcement and retry logic."""
    
    def __init__(self):
        config = get_config()
        
        self.client = AzureOpenAI(
            api_key=config.azure_openai_api_key,
            api_version=config.azure_openai_api_version,
            azure_endpoint=config.azure_openai_endpoint,
        )
        self.deployment = config.azure_openai_deployment_name
    
    def invoke_json(
        self, 
        system_prompt: str, 
        user_prompt: str,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Invoke the model and parse the response as JSON with retry logic.
        
        Args:
            system_prompt: Instructions for the assistant
            user_prompt: User's request
            max_retries: Number of retries on JSON parse failure
            
        Returns:
            Parsed JSON as a dictionary
            
        Raises:
            JSONParseError: If JSON parsing fails after all retry attempts
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            # Build the prompt
            if attempt == 0:
                combined_prompt = f"""Instructions: {system_prompt}

User Request: {user_prompt}

IMPORTANT: Respond with valid JSON only. No markdown, no code fences, no additional text."""
            else:
                # Retry prompt with emphasis on JSON
                combined_prompt = f"""Instructions: {system_prompt}

User Request: {user_prompt}

CRITICAL: Your previous response was invalid JSON. You MUST return ONLY valid JSON.
Do NOT include any text before or after the JSON.
Do NOT wrap in markdown code fences.
Return ONLY the raw JSON object."""

            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "user", "content": combined_prompt}
                ],
                temperature=0.7,
                max_tokens=4096,
            )
            
            content = response.choices[0].message.content
            
            if not content:
                last_error = JSONParseError("Model returned empty content")
                continue
            
            try:
                return self._parse_json_robust(content)
            except JSONParseError as e:
                last_error = e
                continue
        
        # All retries exhausted
        raise last_error or JSONParseError("Failed to get valid JSON after retries")
    
    def invoke_text(
        self,
        system_prompt: str,
        user_prompt: str,
        chat_history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Invoke the model for text (non-JSON) response.
        
        Args:
            system_prompt: Instructions for the assistant
            user_prompt: User's current message
            chat_history: Optional list of previous messages [{"role": "user/assistant", "content": "..."}]
            
        Returns:
            Text response from the model
        """
        messages = [{"role": "system", "content": system_prompt}]
        
        # Add chat history if provided
        if chat_history:
            for turn in chat_history:
                messages.append({
                    "role": turn.get("role", "user"),
                    "content": turn.get("content", "")
                })
        
        # Add current user message
        messages.append({"role": "user", "content": user_prompt})
        
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
        )
        
        content = response.choices[0].message.content
        return content or ""
    
    def _parse_json_robust(self, text: str) -> Dict[str, Any]:
        """
        Parse JSON with multiple repair strategies.
        
        Args:
            text: Raw text that should contain JSON
            
        Returns:
            Parsed JSON dictionary
            
        Raises:
            JSONParseError: If all parsing attempts fail
        """
        # Strategy 1: Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # Strategy 2: Extract JSON from markdown code blocks
        repaired = self._extract_json_block(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        
        # Strategy 3: Find JSON object boundaries
        repaired = self._extract_json_boundaries(text)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
        
        # Strategy 4: Repair common issues
        repaired = self._repair_json(repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            raise JSONParseError(
                f"Failed to parse JSON from model response. Error: {e}\n"
                f"Response preview: {text[:500]}..."
            )
    
    def _extract_json_block(self, text: str) -> str:
        """Extract JSON from markdown code blocks."""
        # Try to find ```json ... ``` blocks
        pattern = r'```(?:json)?\s*\n?(.*?)\n?```'
        matches = re.findall(pattern, text, re.DOTALL)
        if matches:
            return matches[0].strip()
        return text
    
    def _extract_json_boundaries(self, text: str) -> str:
        """Extract content between first { and last }."""
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return text[first_brace:last_brace + 1]
        
        return text
    
    def _repair_json(self, text: str) -> str:
        """Apply common JSON repairs."""
        repaired = text
        
        # Replace smart quotes with regular quotes
        repaired = repaired.replace('"', '"').replace('"', '"')
        repaired = repaired.replace(''', "'").replace(''', "'")
        
        # Remove trailing commas before } or ]
        repaired = re.sub(r',\s*([}\]])', r'\1', repaired)
        
        # Fix unescaped newlines in strings (basic attempt)
        # This is tricky - we'll try to escape literal newlines within strings
        
        # Remove control characters except \n, \r, \t
        repaired = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', repaired)
        
        return repaired


# Global client instance
_client: Optional[AzureOpenAIClient] = None


def get_azure_client() -> AzureOpenAIClient:
    """Get the global Azure OpenAI client instance."""
    global _client
    if _client is None:
        _client = AzureOpenAIClient()
    return _client
