"""Google Gemini provider adapter for SunkGuard.

Strictly adheres to Correction 19:
- Kept outside the core scheduler.
- Zero dependency on live credentials for simulation: if GEMINI_API_KEY is not set,
  gracefully reports simulated fallback without throwing exceptions.
- When GEMINI_API_KEY is available, executes live model calls using google-genai / urllib,
  measures actual input and output tokens consumed, and verifies guardrail caps
  (GEMINI_CALL_CAP, GEMINI_TOKEN_CAP).
"""

import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional
import urllib.request
import urllib.error


@dataclass
class GeminiUsageResult:
    success: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    response_text: str
    is_live: bool
    error: Optional[str] = None


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class GeminiProviderAdapter:
    """Manages real vs simulated Gemini execution outside the core scheduler."""

    def __init__(self, api_key: Optional[str] = None):
        if api_key is not None:
            self.api_key = api_key
        else:
            # Ensure .env is re-read if modified
            if not os.environ.get("GEMINI_API_KEY"):
                env_file = Path(__file__).resolve().parent.parent / ".env"
                if env_file.exists():
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                os.environ[k.strip()] = v.strip()

            self.api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.model = os.environ.get("GEMINI_MODEL", "gemini-1.5-pro").strip()
        self.call_cap = int(os.environ.get("GEMINI_CALL_CAP", "100"))
        self.token_cap = int(os.environ.get("GEMINI_TOKEN_CAP", "500000"))
        self.calls_made = 0
        self.tokens_used = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def execute_prompt(self, prompt: str, max_tokens: int = 1000) -> GeminiUsageResult:
        """Executes a model prompt.
        
        If GEMINI_API_KEY is present, issues a real HTTP request to the Gemini API.
        Otherwise, returns a deterministic simulated usage result.
        """
        if not self.is_configured:
            # Deterministic simulation without credentials
            est_tokens = len(prompt.split()) * 4 + 150
            return GeminiUsageResult(
                success=True,
                prompt_tokens=len(prompt.split()) * 4,
                completion_tokens=150,
                total_tokens=est_tokens,
                response_text="[Simulated response: Gemini credentials not provided. Core engine simulated successfully.]",
                is_live=False,
            )

        if self.calls_made >= self.call_cap:
            return GeminiUsageResult(
                success=False,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_text="",
                is_live=True,
                error=f"GEMINI_CALL_CAP ({self.call_cap}) reached.",
            )

        if self.tokens_used >= self.token_cap:
            return GeminiUsageResult(
                success=False,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_text="",
                is_live=True,
                error=f"GEMINI_TOKEN_CAP ({self.token_cap}) reached.",
            )

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            self.calls_made += 1
            usage = data.get("usageMetadata", {})
            prompt_tok = usage.get("promptTokenCount", len(prompt.split()) * 4)
            cand_tok = usage.get("candidatesTokenCount", 100)
            total_tok = usage.get("totalTokenCount", prompt_tok + cand_tok)
            self.tokens_used += total_tok

            candidates = data.get("candidates", [])
            text = ""
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    text = parts[0].get("text", "")

            return GeminiUsageResult(
                success=True,
                prompt_tokens=prompt_tok,
                completion_tokens=cand_tok,
                total_tokens=total_tok,
                response_text=text,
                is_live=True,
            )
        except Exception as e:
            return GeminiUsageResult(
                success=False,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                response_text="",
                is_live=True,
                error=str(e),
            )
