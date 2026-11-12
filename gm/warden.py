"""The AI Warden — the game-master brain.

Thin wrapper over the LLM client that runs the two prompt roles (referee and
narrator) plus AI-player decisions. It contains NO rules logic and NO dice —
those live in the engine and ruleset. That separation is the whole point.
"""
from __future__ import annotations

from gm import prompts
from gm.client import LLMError


class Warden:
    def __init__(self, client, ruleset):
        self.client = client
        self.ruleset = ruleset

    def adjudicate(self, state, actor_name: str, action: str) -> dict:
        return self.client.complete_json(
            prompts.referee_system(self.ruleset),
            prompts.referee_user(state, actor_name, action),
        )

    def narrate(self, state, actor_name: str, action: str, results: list[dict]) -> dict:
        return self.client.complete_json(
            prompts.narrator_system(self.ruleset),
            prompts.narrator_user(state, actor_name, action, results),
        )

    def opening(self, state, premise: str) -> dict:
        return self.client.complete_json(
            prompts.narrator_system(self.ruleset),
            prompts.opening_user(state, premise),
        )

    def ai_player_action(self, state, character) -> dict:
        return self.client.complete_json(
            prompts.ai_player_system(self.ruleset),
            prompts.ai_player_user(state, character),
        )
