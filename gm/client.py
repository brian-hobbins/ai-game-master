"""Swappable LLM client for the AI Warden.

Same two-backend design as the triage agent:

* **cli** (default): drives the authenticated `claude` CLI — uses your Claude
  subscription, no API key. Great for playing locally.
* **api**: official Anthropic SDK with ANTHROPIC_API_KEY — cheaper/faster per
  call, the right choice for a hosted game.

Select with AIGM_BACKEND = cli | api | auto (auto picks api when
ANTHROPIC_API_KEY is set, else cli). The Warden always returns JSON, so both
backends expose `complete_json(system, user) -> dict`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"Could not parse JSON from model output: {exc}") from exc
    raise LLMError("Model did not return JSON.")


class CLIClient:
    def __init__(self, timeout: int = 180):
        self.bin = shutil.which("claude")
        if not self.bin:
            raise LLMError(
                "`claude` CLI not found on PATH. Install Claude Code, or set "
                "ANTHROPIC_API_KEY and AIGM_BACKEND=api."
            )
        self.timeout = timeout

    def complete_json(self, system: str, user: str) -> dict:
        cmd = [self.bin, "-p", "--output-format", "json"]
        if system:
            cmd += ["--append-system-prompt", system]
        try:
            proc = subprocess.run(cmd, input=user, capture_output=True,
                                  text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"claude CLI timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise LLMError(f"claude CLI failed: {proc.stderr.strip() or proc.stdout.strip()}")
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Unexpected CLI output: {exc}") from exc
        if envelope.get("is_error"):
            raise LLMError(f"claude CLI reported an error: {envelope.get('result')}")
        return _extract_json(envelope.get("result", ""))


class APIClient:
    def __init__(self, model: str = "claude-opus-5-5", max_tokens: int = 2048):
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:
            raise LLMError("`anthropic` package not installed (pip install anthropic), "
                           "or use the CLI backend.") from exc
        self._anthropic = __import__("anthropic")
        from anthropic import Anthropic
        self.client = Anthropic()
        self.model = model
        self.max_tokens = max_tokens

    def complete_json(self, system: str, user: str) -> dict:
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                thinking={"type": "adaptive"},
                system=system, messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return _extract_json(text)


def get_client(backend: str | None = None):
    backend = (backend or os.environ.get("AIGM_BACKEND", "auto")).lower()
    if backend == "auto":
        backend = "api" if os.environ.get("ANTHROPIC_API_KEY") else "cli"
    if backend == "cli":
        return CLIClient()
    if backend == "api":
        return APIClient()
    raise LLMError(f"Unknown backend {backend!r} (use cli, api, or auto)")
