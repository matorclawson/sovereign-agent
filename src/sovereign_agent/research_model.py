"""Bounded research turns through the existing, operator-selected subscription.

No new credential store or provider service. Model/usage are checked from the
terminal receipt; a CLI cost valuation is not an invoice or a billing ceiling.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from sovereign_agent.model_turn import Message, ModelError, ModelTurn
from sovereign_agent.providers.base import InvocationRequest, allowed_environment, has_flag
from sovereign_agent.providers.claude import ClaudeProvider

MODEL = "claude-fable-5-1"


class SubscriptionModel:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.last_receipt: dict[str, Any] = {}

    def complete(
        self,
        messages: list[Message],
        tools: list[Message],
        *,
        timeout: float,
        max_output_tokens: int,
    ) -> ModelTurn:
        started = time.monotonic()
        if tools or any(os.environ.get(k) for k in ClaudeProvider.authentication_environment):
            raise ModelError("subscription route refuses tools and credential overrides")
        env = allowed_environment("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TMPDIR")
        env.update(
            CLAUDE_CODE_MAX_TURNS="1",
            CLAUDE_CODE_MAX_RETRIES="0",
            CLAUDE_CODE_MAX_OUTPUT_TOKENS=str(max_output_tokens),
            MAX_STRUCTURED_OUTPUT_RETRIES="0",
        )
        provider = ClaudeProvider()
        caps = provider.probe(env=env)
        flags = [
            "--model",
            "--safe-mode",
            "--restricted",
            "--tools",
            "--strict-mcp-config",
            "--mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--setting-sources",
        ]
        if not caps.available or not all(has_flag(caps.evidence[1].text, flag) for flag in flags):
            raise ModelError("installed provider cannot prove required restricted print flags")
        request = InvocationRequest(
            workspace=self.root,
            output=self.root / "provider-output",
            prompt=str(messages[-1]["content"]),
        )
        spec = provider.build_invocation(request, env=env)
        argv = spec.argv[:-1] + [
            "--model",
            MODEL,
            "--safe-mode",
            "--restricted",
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--disable-slash-commands",
            "--no-session-persistence",
            "--setting-sources",
            "",
            "--system-prompt",
            str(messages[0]["content"]),
            spec.argv[-1],
        ]
        self.last_receipt = {
            "requested_model": MODEL,
            "client": caps.version,
            "route": "existing claude.ai subscription; operator-selected",
            "budget_flag": "omitted per explicit operator route approval",
            "max_output_tokens": max_output_tokens,
        }
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise ModelError("provider capability checks exhausted turn time")
        try:
            result = subprocess.run(
                argv, cwd=spec.cwd, env=env, capture_output=True, text=True, timeout=remaining
            )
        except subprocess.TimeoutExpired:
            self.last_receipt["status"] = "TIMEOUT_USAGE_UNKNOWN"
            raise ModelError("subscription turn timed out; usage unknown") from None
        self.last_receipt.update(
            exit=result.returncode,
            stderr_sha256=hashlib.sha256(result.stderr.encode()).hexdigest(),
            wall_seconds=time.monotonic() - started,
        )
        events = [provider.parse_event(line) for line in result.stdout.splitlines()]
        terminal = next((e for e in events if e and e.terminal), None)
        observed = next((e.payload.get("model") for e in events if e and e.kind == "system"), None)
        self.last_receipt["observed_model"] = observed
        if not terminal:
            raise ModelError("subscription returned no terminal usage receipt")
        payload = terminal.payload
        self.last_receipt.update(
            status=payload.get("subtype"),
            usage=terminal.usage,
            turns=payload.get("num_turns"),
            api_price_valuation_usd=payload.get("total_cost_usd"),
        )
        tokens, content = terminal.usage.get("output_tokens"), payload.get("result")
        if (
            result.returncode
            or not terminal.succeeded
            or observed != MODEL
            or payload.get("num_turns") != 1
            or type(tokens) is not int
            or not 0 <= tokens <= max_output_tokens
            or not isinstance(content, str)
        ):
            raise ModelError("subscription model, turn, terminal status or usage refused")
        return ModelTurn(content=content, output_tokens=tokens)
