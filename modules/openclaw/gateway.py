"""Client for the real OpenClaw gateway used by the advertising agents.

Every reasoning agent (goal, planner, evaluator, optimizer calibrator, market
researcher, image art director) is a dedicated OpenClaw agent on the gateway.
Each role has its own agent id and its own session key, so the goal agent's
memory does not leak into the planner's and both stay scoped to one store.

There is deliberately no direct-OpenAI path and no in-code fallback: if the
gateway is not configured, is unreachable, or answers with something that is
not the JSON the agent contract requires, the caller gets an HTTP error. The
advertising agents are not allowed to invent a goal, a plan or an assessment
when the model behind them could not be reached.

Environment:

    OPENCLAW_GATEWAY_URL      e.g. http://openclaw:18789
    OPENCLAW_GATEWAY_TOKEN    bearer token (gateway.auth.token)
    OPENCLAW_GOAL_AGENT_MODEL        default: openclaw/ads-goal
    OPENCLAW_PLANNER_AGENT_MODEL     default: openclaw/ads-planner
    OPENCLAW_EVALUATOR_AGENT_MODEL   default: openclaw/ads-evaluator
    OPENCLAW_CALIBRATOR_AGENT_MODEL  default: openclaw/ads-calibrator
    OPENCLAW_RESEARCH_AGENT_MODEL    default: openclaw/ads-research
    OPENCLAW_IMAGE_AGENT_MODEL       default: openclaw/ads-image
    HERMES_GATEWAY_URL        optional: send the six ad roles to Hermes profiles
    HERMES_GATEWAY_TOKEN      Hermes API_SERVER_KEY (falls back to the OpenClaw token)

"openclaw/<agentId>" selects a dedicated agent on the gateway; a bare
"openclaw" would use the gateway's default agent.

With HERMES_GATEWAY_URL set, each ad role is sent to
`<hermes>/p/<agentId>/v1/chat/completions` - a Hermes profile per role - and the
model id is the bare agent id. The pharmacy WhatsApp agent keeps using
the OpenClaw gateway regardless.

Image generation itself is a media model, not a language model, so it stays a
tool in the backend. What the image should look like - the art direction and
prompt - is the ads-image agent's judgement, and the reference photos are
chosen by the same agent (multimodal user turns, see `images` below).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# role -> (env var, default model selector)
_ROLES = {
    "goal": ("OPENCLAW_GOAL_AGENT_MODEL", "openclaw/ads-goal"),
    "planner": ("OPENCLAW_PLANNER_AGENT_MODEL", "openclaw/ads-planner"),
    "evaluator": ("OPENCLAW_EVALUATOR_AGENT_MODEL", "openclaw/ads-evaluator"),
    "calibrator": ("OPENCLAW_CALIBRATOR_AGENT_MODEL", "openclaw/ads-calibrator"),
    "research": ("OPENCLAW_RESEARCH_AGENT_MODEL", "openclaw/ads-research"),
    "image": ("OPENCLAW_IMAGE_AGENT_MODEL", "openclaw/ads-image"),
}

DEFAULT_TIMEOUT = 180.0


def _role(role: str) -> tuple:
    try:
        return _ROLES[role]
    except KeyError:
        raise ValueError(f"Unknown OpenClaw agent role: {role!r}") from None


def agent_model(role: str) -> str:
    """The gateway model selector for one agent role."""
    env_name, default = _role(role)
    return (os.getenv(env_name) or default).strip()


def agent_id(role: str) -> str:
    """The agent id without the "openclaw/" prefix (useful for session keys/logs)."""
    return agent_model(role).split("/", 1)[-1]


def gateway_url() -> str:
    url = (os.getenv("OPENCLAW_GATEWAY_URL") or "").strip().rstrip("/")
    if not url:
        raise HTTPException(
            status_code=503,
            detail="OPENCLAW_GATEWAY_URL is not configured. The advertising agents run on "
                   "the OpenClaw gateway and have no local fallback.",
        )
    return url


def gateway_token() -> str:
    token = (os.getenv("OPENCLAW_GATEWAY_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="OPENCLAW_GATEWAY_TOKEN is not configured. The advertising agents run on "
                   "the OpenClaw gateway and have no local fallback.",
        )
    return token


def ensure_configured() -> None:
    """Fail fast (before any work or session is created) when the gateway is unset."""
    gateway_url()
    gateway_token()


def output_error(role: str, reason: str) -> HTTPException:
    """502 for an agent that answered, but not with a usable answer."""
    return HTTPException(
        status_code=502,
        detail=f"OpenClaw {agent_id(role)} agent returned an unusable answer: {reason}",
    )


def hermes_base() -> str | None:
    """Optional Hermes gateway for the six ad roles (HERMES_GATEWAY_URL).

    When set, goal/planner/evaluator/calibrator/research/image are sent to their
    own Hermes profile endpoint (`/p/<agent>/v1/chat/completions`) instead of the
    OpenClaw gateway. The pharmacy agent always stays on OpenClaw."""
    return (os.getenv("HERMES_GATEWAY_URL") or "").strip().rstrip("/") or None


def hermes_token() -> str:
    token = (os.getenv("HERMES_GATEWAY_TOKEN") or os.getenv("OPENCLAW_GATEWAY_TOKEN") or "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="HERMES_GATEWAY_URL is set but neither HERMES_GATEWAY_TOKEN nor "
                   "OPENCLAW_GATEWAY_TOKEN is configured.",
        )
    return token


def _target(role: str) -> tuple:
    """(url, token, model) for one agent turn, honouring the optional Hermes backend."""
    base = hermes_base()
    if base and role in _ROLES:
        agent = agent_id(role)
        return f"{base}/p/{agent}/v1/chat/completions", hermes_token(), agent
    return f"{gateway_url()}/v1/chat/completions", gateway_token(), agent_model(role)


def _headers(session_key: str, token: str) -> dict:
    """Both session headers are sent: OpenClaw reads X-OpenClaw-Session-Key,
    Hermes uses X-Hermes-Session-Key, and each ignores the other's."""
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-OpenClaw-Session-Key": session_key,
        "X-Hermes-Session-Key": session_key,
    }


def _payload(model: str, system_prompt: str, user_text: str,
             images: list | None = None) -> dict:
    """One chat-completions payload; `images` become image_url parts of the user
    turn (public URLs or data: URIs) so a vision-capable gateway agent can look
    at the business's real photos instead of choosing blind."""
    if images:
        content: Any = [{"type": "text", "text": user_text or "Continue."}]
        content += [{"type": "image_url", "image_url": {"url": url}}
                    for url in images if url]
    else:
        content = user_text or "Continue."
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
    }


def _content(data: Any, role: str) -> str:
    try:
        message = data["choices"][0]["message"]
        content = message.get("content")
        if isinstance(content, list):  # some gateways return content parts
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        text = (content or "").strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        text = ""
    if not text:
        raise output_error(role, "empty completion")
    return text


def _parse_json(text: str, role: str, expect: str) -> Any:
    """Strict JSON parse of an agent answer.

    A code fence or a sentence around the payload is tolerated; anything else is
    an error. There is no empty-object fallback - a fabricated goal or plan is
    worse than a visible failure.
    """
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    pattern = r"\[[\s\S]*\]" if expect == "array" else r"\{[\s\S]*\}"
    match = re.search(pattern, cleaned)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            pass
    excerpt = " ".join(text.split())[:200]
    raise output_error(role, f"expected JSON {expect}, got: {excerpt!r}")


def _response_json(resp: httpx.Response, role: str) -> Any:
    if resp.status_code >= 400:
        logger.error("[OpenClaw][%s] gateway returned %s: %s", role, resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=502,
            detail=f"OpenClaw {agent_id(role)} agent failed ({resp.status_code}): {resp.text[:300]}",
        )
    try:
        return resp.json()
    except ValueError:
        raise output_error(role, "gateway response was not JSON") from None


def _transport_error(exc: Exception, role: str) -> HTTPException:
    logger.error("[OpenClaw][%s] gateway unreachable: %s", role, exc)
    return HTTPException(
        status_code=503,
        detail=f"OpenClaw gateway unreachable for the {agent_id(role)} agent: {type(exc).__name__}",
    )


async def ask(
    role: str,
    session_key: str,
    system_prompt: str,
    user_text: str,
    timeout: float = DEFAULT_TIMEOUT,
    images: list | None = None,
) -> str:
    """One turn on one agent. Raises 503/502 - never falls back."""
    url, token, model = _target(role)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(
                url,
                headers=_headers(session_key, token),
                json=_payload(model, system_prompt, user_text, images),
            )
    except httpx.RequestError as exc:
        raise _transport_error(exc, role) from exc
    return _content(_response_json(resp, role), role)


async def ask_json(
    role: str,
    session_key: str,
    system_prompt: str,
    user_text: str,
    expect: str = "object",
    timeout: float = DEFAULT_TIMEOUT,
    images: list | None = None,
) -> Any:
    return _parse_json(
        await ask(role, session_key, system_prompt, user_text, timeout, images), role, expect
    )


def ask_sync(
    role: str,
    session_key: str,
    system_prompt: str,
    user_text: str,
    timeout: float = DEFAULT_TIMEOUT,
    images: list | None = None,
) -> str:
    """Blocking variant for callers that are not in the event loop (optimizer loop)."""
    url, token, model = _target(role)
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            resp = client.post(
                url,
                headers=_headers(session_key, token),
                json=_payload(model, system_prompt, user_text, images),
            )
    except httpx.RequestError as exc:
        raise _transport_error(exc, role) from exc
    return _content(_response_json(resp, role), role)


def ask_json_sync(
    role: str,
    session_key: str,
    system_prompt: str,
    user_text: str,
    expect: str = "object",
    timeout: float = DEFAULT_TIMEOUT,
    images: list | None = None,
) -> Any:
    return _parse_json(
        ask_sync(role, session_key, system_prompt, user_text, timeout, images), role, expect
    )
