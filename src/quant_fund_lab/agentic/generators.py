"""Strategy generators supporting both IDE Agent workflow (Antigravity/Codex) and headless LLM APIs."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .evolutionary_generator import EvolutionaryStrategyGenerator
from .schemas import StrategyContract


def extract_json_payload(text: str) -> str:
    """Extract JSON object from LLM response containing markdown code blocks or explanatory text."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    match_braces = re.search(r"(\{.*\})", text, re.DOTALL)
    if match_braces:
        return match_braces.group(1).strip()
    return text


@dataclass
class FileBridgeGenerator:
    """Generator bridge for IDE subscription agents (Antigravity / Codex).

    Instead of spending external API tokens, this writes the evolutionary prompt, AST DSL spec,
    and trailing diagnostics to a workspace file. The IDE agent reads it, formulates the next
    hypothesis, and writes proposal.json for deterministic evaluation.
    """

    workspace_dir: Path

    def __init__(self, workspace_dir: str | Path = "evolution_workspace") -> None:
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def write_task_prompt(
        self,
        archetype: str,
        round_num: int,
        system_prompt: str,
        user_prompt: str,
    ) -> Path:
        """Write current reflection prompt to file for IDE agent inspection."""
        prompt_file = self.workspace_dir / f"prompt_{archetype}_round_{round_num}.md"
        content = (
            f"# Strategy Evolution Task - Archetype: {archetype} (Round {round_num})\n\n"
            f"## System Role & Rules\n{system_prompt}\n\n"
            f"## Trailing Diagnostics & Request\n{user_prompt}\n\n"
            f"## Submission Guide\n"
            f"Write your proposed JSON to: `{self.workspace_dir / f'proposal_{archetype}.json'}`\n"
        )
        prompt_file.write_text(content, encoding="utf-8")
        return prompt_file

    def read_proposal(self, archetype: str) -> StrategyContract:
        """Read and validate the proposal written by the IDE agent."""
        proposal_file = self.workspace_dir / f"proposal_{archetype}.json"
        if not proposal_file.exists():
            raise FileNotFoundError(
                f"Expected agent proposal at {proposal_file}. "
                "Ensure the IDE agent has written the StrategyContract JSON."
            )
        raw_text = proposal_file.read_text(encoding="utf-8")
        clean_json = extract_json_payload(raw_text)
        return StrategyContract.model_validate_json(clean_json)

    def __call__(self, system_prompt: str, user_prompt: str) -> StrategyContract:
        """Standard Protocol call for reflection loop."""
        # Check if default proposal exists
        default_file = self.workspace_dir / "proposal.json"
        if default_file.exists():
            clean_json = extract_json_payload(default_file.read_text(encoding="utf-8"))
            return StrategyContract.model_validate_json(clean_json)
        # Otherwise write prompt to workspace
        task_path = self.workspace_dir / "current_task_prompt.md"
        task_path.write_text(
            f"# Reflection Prompt\n\n{system_prompt}\n\n---\n\n{user_prompt}\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            f"IDE Agent prompt written to {task_path}. "
            f"Please populate '{default_file}' with StrategyContract JSON to proceed."
        )


class APIStrategyGenerator:
    """Headless LLM API generator compatible with OpenAI, DeepSeek, OpenRouter, and Ollama."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        temperature: float = 0.5,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY") or ""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def _call_api(self, messages: list[dict[str, str]]) -> str:
        """Execute HTTP POST request to completions endpoint."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return str(data["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM API Error ({e.code}): {err_msg}") from e

    def __call__(self, system_prompt: str, user_prompt: str) -> StrategyContract:
        """Generate StrategyContract via LLM API with automated JSON schema retry."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                raw_response = self._call_api(messages)
                clean_json = extract_json_payload(raw_response)
                return StrategyContract.model_validate_json(clean_json)
            except (ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError, RuntimeError) as e:
                last_error = e
                if attempt < self.max_retries:
                    messages.append({"role": "assistant", "content": raw_response if "raw_response" in locals() else ""})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"JSON validation failed with error: {e}. "
                            "Please fix schema errors and output ONLY valid StrategyContract JSON."
                        ),
                    })

        raise RuntimeError(f"Failed to generate valid StrategyContract after {self.max_retries} retries: {last_error}")


__all__ = [
    "APIStrategyGenerator",
    "EvolutionaryStrategyGenerator",
    "FileBridgeGenerator",
    "extract_json_payload",
]
