"""Advertising agents on the real OpenClaw gateway.

Goal, planner, evaluator, art director (ads-image) and market researcher
(ads-research) are separate agents on the gateway (see
modules/openclaw/gateway.py). Each gets a per-store session key so it keeps its
own memory, and each is asked for a strict JSON contract that is validated
here. Nothing is fabricated locally: a missing gateway, an empty completion or
an unparseable answer raises instead of producing a default goal, a default
plan or a default "completed" assessment.

The executor is not an agent: it dispatches the skill/action the planner named
(_run_executor_task in router.py) and never re-decides anything.

The optimizer's target calibration is the calibrator agent; it lives in
modules/optimizer/calibration.py and uses the same gateway client. The market
researcher is used by modules/market_research/service.py, and the art director
by the ad-creator image action, asset generation and campaign creative.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.openclaw import gateway

logger = logging.getLogger(__name__)

GOAL_TYPES = {
    "maximize_roas",
    "minimize_cpa",
    "increase_conversions",
    "grow_audience",
    "reduce_cac",
    "improve_lead_quality",
    "scale_revenue",
    "brand_awareness",
}
PRIORITIES = {"critical", "high", "medium", "low"}
ASSESSMENTS = {"on_track", "at_risk", "off_track", "achieved", "failed"}
RECOMMENDATION_TYPES = {"scale", "reduce", "pivot", "pause", "continue", "abandon"}

# The executor contract: exactly what _dispatch_ad_creator / _dispatch_zernio in
# router.py can execute. A plan naming anything else cannot run, so the planner
# is only offered these.
SKILL_ACTIONS: Dict[str, Dict[str, Any]] = {
    "ad-creator": {
        "description": "AI-powered ad creation and market research",
        "actions": {
            "research_market": ["store_id"],
            "generate_ad_copy": ["store_id", "product_name", "product_description"],
            "generate_whatsapp_copy": ["store_id", "product_name", "product_description"],
            "generate_image": ["store_id", "product_name", "product_description"],
            "generate_full_campaign": ["store_id", "product_name", "product_description"],
        },
    },
    "zernio-ads": {
        "description": "Meta Ads management via Zernio API",
        "actions": {
            "list_connected_accounts": [],
            "get_all_store_insights": ["profile_id", "date_preset"],
            "get_insights": ["ad_account_id"],
            "get_conversion_stats": ["profile_id"],
            "create_campaign": ["account_id", "ad_account_id", "name", "goal", "budget", "targeting"],
            "create_ctwa_campaign": ["account_id", "ad_account_id", "name", "budget"],
            "pause_ad": ["ad_id"],
            "update_campaign": ["campaign_id", "updates"],
            "scale_budget": ["campaign_id", "new_budget"],
        },
    },
}

_METRIC_LABELS = [
    ("roas", "ROAS", "x"),
    ("cpa", "CPA", "$"),
    ("ctr", "CTR", ""),
    ("conversion_rate", "conversion rate", ""),
    ("conversions", "conversions", ""),
    ("clicks", "clicks", ""),
    ("active_campaigns", "active campaigns", ""),
    ("total_spend", "spend", "$"),
    ("total_revenue", "revenue", "$"),
    ("date_range", "date range", ""),
]


def _fmt_metrics(performance: Optional[Dict[str, Any]]) -> str:
    """Only the numbers that are actually known - never a stand-in zero."""
    lines = []
    for key, label, prefix in _METRIC_LABELS:
        value = (performance or {}).get(key)
        if value is None or value == "":
            continue
        lines.append(f"- {label}: {prefix}{value}")
    return "\n".join(lines) if lines else "- no performance data available"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_money(value: Any) -> str:
    amount = _num(value)
    return f"${amount:.2f}" if amount is not None else "not specified"


def _session_key(role: str, store_id: str) -> str:
    return f"ads-{role}:{store_id or 'unknown-store'}"


# ============================== Goal Agent ==============================

GOAL_AGENT_PROMPT = """You are the Strategic Advertising Goal Setter for one e-commerce store.

You run as the dedicated OpenClaw goal agent. You are given the store's business profile,
its recent advertising performance, and its budget constraints. Set clear, achievable
advertising goals from that evidence. Use any research/search tools configured on you when
you genuinely need current benchmarks for this niche and market; do not invent a benchmark
or a performance number.

Goal types you may use: maximize_roas, minimize_cpa, increase_conversions, grow_audience,
reduce_cac, improve_lead_quality, scale_revenue, brand_awareness.

Rules:
1. Base targets on the performance given. Do not assume numbers that were not provided.
2. Respect the budget constraints.
3. Balance short-term wins with long-term growth.
4. Return 1 to 5 goals, at least one achievable within 7 days.
5. Every "reasoning" must cite the evidence you actually used (a metric given to you, the
   business profile, or something a tool really returned). If the evidence is too thin to
   justify a precise target, set a conservative target and say so.

Return ONLY a JSON array, no prose and no code fence. Each goal:
{"type": "...", "description": "...", "target_metric": "...", "target_value": 0,
 "deadline": "ISO date string", "priority": "critical|high|medium|low", "reasoning": "..."}
"""


async def generate_goals(
    store_id: str,
    performance: Dict[str, Any],
    constraints: Dict[str, Any],
    store_name: str = "",
    niche: str = "",
    country: str = "",
    business: str = "",
) -> List[Dict[str, Any]]:
    """Ask the goal agent for this store's goals. Raises when there is no real answer."""
    prompt = (
        f"Store: {store_name or store_id}\n"
        f"Niche / market: {niche or 'unknown'} / {country or 'unknown'}\n"
        + (f"Business profile (authoritative, already known): {business}\n" if business else "")
        + "\nRecent advertising performance:\n"
        + _fmt_metrics(performance)
        + "\n\nConstraints:\n"
        + f"- total budget cap: {_fmt_money(constraints.get('max_budget'))}\n"
        + f"- daily spend cap: {_fmt_money(constraints.get('max_daily_spend'))}\n"
        + "\nSet the goals for this store."
    )
    raw = await gateway.ask_json(
        "goal",
        _session_key("goal", store_id),
        GOAL_AGENT_PROMPT,
        prompt,
        expect="array",
        timeout=180.0,
    )
    if not isinstance(raw, list):
        raise gateway.output_error("goal", "expected a JSON array of goals")

    now = datetime.utcnow()
    goals: List[Dict[str, Any]] = []
    for index, item in enumerate(raw[:5]):
        if not isinstance(item, dict):
            logger.warning("[OpenClaw][goal] dropping non-object goal entry: %r", item)
            continue
        goal_type = str(item.get("type") or "").strip()
        if goal_type not in GOAL_TYPES:
            logger.warning("[OpenClaw][goal] dropping goal with unknown type %r", goal_type)
            continue
        target_value = _num(item.get("target_value"))
        if target_value is None:
            logger.warning("[OpenClaw][goal] dropping goal without a numeric target_value")
            continue
        priority = str(item.get("priority") or "medium").lower()
        target_metric = str(item.get("target_metric") or "").strip()
        goals.append({
            "id": f"goal-{int(now.timestamp())}-{index}",
            "type": goal_type,
            "description": str(item.get("description") or "").strip(),
            "target_metric": target_metric,
            "target_value": target_value,
            "current_value": (performance or {}).get(target_metric),
            "deadline": item.get("deadline"),
            "priority": priority if priority in PRIORITIES else "medium",
            "status": "pending",
            "reasoning": str(item.get("reasoning") or "").strip(),
            "created_at": now.isoformat(),
        })

    if not goals:
        raise gateway.output_error("goal", "no goal in the answer was a valid typed, numeric goal")
    return goals


# ============================= Planner Agent =============================

PLANNER_AGENT_PROMPT = f"""You are the Strategic Advertising Planner for one e-commerce store.

You turn a single goal into an execution plan built only from the skills and actions below.
You run as the dedicated OpenClaw planner agent; a deterministic executor will later run the
tasks exactly as you write them, so every task must be executable as given.

Available skills and actions (skill -> action -> parameters it needs):
{json.dumps(SKILL_ACTIONS, indent=2)}

Rules:
1. Research before creating campaigns.
2. Include monitoring/reporting tasks so progress can be checked.
3. Respect the available budget.
4. Return at most 15 tasks.
5. For zernio-ads tasks, use only real account ids from the connected-accounts context.
   Never invent an account_id, ad_account_id, profile_id or pixel_id. If no connected
   account is available, use a research or reporting task instead and say what is missing
   in "fallback_strategy".
6. "budget" is a plain number (20, not {{"daily": 20}}).
7. Fill ad-creator parameters from the business profile. Never write "unknown" or
   "determine through research".
8. Never write {{{{task_N.field}}}} template placeholders. The executor passes earlier task
   results forward itself; simply omit parameters that depend on them.
9. Campaign and ad names must read like a person wrote them: no "|" separators and no em or
   en dashes.
10. Do not write an image prompt: the ads-image agent writes it from the store's real brand.

Return ONLY JSON, no prose and no code fence:
{{"description": "...", "tasks": [{{"type": "...", "description": "...", "skill": "ad-creator|zernio-ads",
"action": "...", "parameters": {{}}, "dependencies": [], "max_retries": 3}}],
"parallel_groups": [["task_0", "task_1"]], "estimated_duration_hours": 24, "estimated_cost": 0,
"success_criteria": [{{"metric": "...", "operator": "gte", "value": 0, "weight": 1}}],
"fallback_strategy": "..."}}
"""


async def generate_plan(
    goal: Dict[str, Any],
    available_budget: float,
    existing_campaigns: Optional[List[dict]] = None,
    store_context: Optional[Dict[str, Any]] = None,
    store_id: str = "",
) -> Dict[str, Any]:
    """Ask the planner agent for this goal's plan. Raises when there is no real answer."""
    store_context = store_context or {}
    accounts = store_context.get("connected_accounts") or []
    business = store_context.get("business") or {}
    prompt = (
        f"## Goal\n"
        f"Type: {goal.get('type')}\n"
        f"Description: {goal.get('description')}\n"
        f"Target: {goal.get('target_metric')} = {goal.get('target_value')}\n"
        f"Current: {goal.get('current_value') if goal.get('current_value') is not None else 'unknown'}\n"
        f"Priority: {goal.get('priority')}\n"
        f"Deadline: {goal.get('deadline') or 'none'}\n\n"
        f"## Budget\nAvailable: {_fmt_money(available_budget)}\n\n"
        f"## Existing campaigns\n{json.dumps((existing_campaigns or [])[:10])}\n\n"
        f"## Business profile\n{json.dumps(business, indent=2)}\n\n"
        f"## Connected accounts (the ONLY real ids allowed in zernio-ads parameters)\n"
        f"profile_id: {store_context.get('profile_id') or 'none'}\n"
        f"ad accounts: {json.dumps(accounts[:10]) if accounts else 'none connected'}\n"
        f"server-resolved ad account: {store_context.get('resolved_ad_account_id') or 'none'}\n\n"
        "Create the execution plan for this goal."
    )
    raw = await gateway.ask_json(
        "planner",
        _session_key("planner", store_id or str(goal.get("id") or "")),
        PLANNER_AGENT_PROMPT,
        prompt,
        expect="object",
        timeout=180.0,
    )
    if not isinstance(raw, dict):
        raise gateway.output_error("planner", "expected a JSON plan object")

    now = datetime.utcnow()
    tasks: List[Dict[str, Any]] = []
    for index, item in enumerate((raw.get("tasks") or [])[:15]):
        if not isinstance(item, dict):
            logger.warning("[OpenClaw][planner] dropping non-object task entry: %r", item)
            continue
        skill = str(item.get("skill") or "").strip()
        action = str(item.get("action") or "").strip()
        if action not in (SKILL_ACTIONS.get(skill) or {}).get("actions", {}):
            logger.warning("[OpenClaw][planner] dropping unexecutable task %s.%s", skill or "?", action or "?")
            continue
        max_retries = _num(item.get("max_retries"))
        tasks.append({
            "id": f"task-{int(now.timestamp())}-{index}",
            "type": str(item.get("type") or "").strip(),
            "description": str(item.get("description") or "").strip(),
            "skill": skill,
            "action": action,
            "parameters": item.get("parameters") if isinstance(item.get("parameters"), dict) else {},
            "dependencies": item.get("dependencies") if isinstance(item.get("dependencies"), list) else [],
            "status": "pending",
            "retry_count": 0,
            "max_retries": max(1, int(max_retries)) if max_retries is not None else 1,
        })

    if not tasks:
        raise gateway.output_error("planner", "the plan contained no task the executor can run")

    return {
        "id": f"plan-{int(now.timestamp())}",
        "goal_id": goal.get("id"),
        "description": str(raw.get("description") or "").strip(),
        "tasks": tasks,
        "parallel_groups": raw.get("parallel_groups") or [],
        "estimated_duration_hours": raw.get("estimated_duration_hours"),
        "estimated_cost": raw.get("estimated_cost"),
        "success_criteria": raw.get("success_criteria") or [],
        "fallback_strategy": str(raw.get("fallback_strategy") or "").strip(),
        "created_at": now.isoformat(),
    }


# ============================ Evaluator Agent =============================

EVALUATOR_AGENT_PROMPT = """You are the Independent Evaluator for an autonomous advertising
session. You run as the dedicated OpenClaw evaluator agent. You did not set the goal and you
did not write the plan, so judge the outcome on the evidence you are given.

You are given one goal, the plan that was executed, the real result of every task (success or
error), and the store's measured performance. Judge whether the goal is being met.

Rules:
1. Use only the numbers and task results in the input. Never estimate a metric that was not
   given, and never claim a task succeeded when it is listed as failed.
2. progress_percentage is your judgement of movement toward the target, from the measured
   current value and the goal's baseline. Say what it is based on in "summary".
3. An assessment of "achieved" requires the measured target to actually be met. If the data
   cannot prove that, choose on_track/at_risk/off_track instead.
4. Recommendations must follow from the evidence. "continue" is valid when the plan is
   working and there is nothing specific to change.
5. should_continue is false only when no further work on this goal can help (achieved, failed,
   or genuinely impossible within the constraints).

Return ONLY JSON, no prose and no code fence:
{"assessment": "on_track|at_risk|off_track|achieved|failed", "progress_percentage": 0,
 "summary": "...", "should_continue": true,
 "recommendations": [{"type": "scale|reduce|pivot|pause|continue|abandon", "reason": "...",
 "priority": "critical|high|medium|low"}]}
"""


async def evaluate_progress(
    goal: Dict[str, Any],
    plan: Dict[str, Any],
    task_results: List[Dict[str, Any]],
    performance: Dict[str, Any],
    store_id: str = "",
    store_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ask the evaluator agent for an assessment of one goal. Raises when there is none."""
    store_context = store_context or {}
    results = []
    for item in task_results[:30]:
        task = item.get("task") or {}
        results.append({
            "task": task.get("description") or task.get("action") or task.get("type") or "",
            "skill": task.get("skill"),
            "action": task.get("action"),
            "success": bool(item.get("success")),
            "result": item.get("result"),
            "error": item.get("error"),
        })
    prompt = (
        f"## Goal\n{json.dumps(goal, indent=2)}\n\n"
        f"## Plan\n{json.dumps({k: plan.get(k) for k in ('description', 'success_criteria', 'fallback_strategy')}, indent=2)}\n\n"
        f"## Task results\n{json.dumps(results, indent=2)}\n\n"
        f"## Measured performance\n{_fmt_metrics(performance)}\n\n"
        f"## Business profile\n{json.dumps(store_context.get('business') or {}, indent=2)}\n\n"
        "Assess this goal."
    )
    raw = await gateway.ask_json(
        "evaluator",
        _session_key("evaluator", store_id or str(goal.get("id") or "")),
        EVALUATOR_AGENT_PROMPT,
        prompt,
        expect="object",
        timeout=180.0,
    )
    if not isinstance(raw, dict):
        raise gateway.output_error("evaluator", "expected a JSON assessment object")

    assessment = str(raw.get("assessment") or "").strip()
    if assessment not in ASSESSMENTS:
        raise gateway.output_error("evaluator", f"invalid assessment {assessment!r}")
    should_continue = raw.get("should_continue")
    if not isinstance(should_continue, bool):
        raise gateway.output_error("evaluator", "should_continue must be a boolean")

    progress = _num(raw.get("progress_percentage"))
    recommendations = []
    for rec in raw.get("recommendations") or []:
        if not isinstance(rec, dict):
            continue
        rec_type = str(rec.get("type") or "").strip()
        if rec_type not in RECOMMENDATION_TYPES:
            logger.warning("[OpenClaw][evaluator] dropping unknown recommendation type %r", rec_type)
            continue
        priority = str(rec.get("priority") or "medium").lower()
        recommendations.append({
            "type": rec_type,
            "reason": str(rec.get("reason") or "").strip(),
            "priority": priority if priority in PRIORITIES else "medium",
        })

    return {
        "goal_id": goal.get("id"),
        "plan_id": plan.get("id"),
        "assessment": assessment,
        # A judgement, clamped to the only range that makes sense.
        "progress_percentage": max(0.0, min(100.0, progress)) if progress is not None else None,
        "summary": str(raw.get("summary") or "").strip(),
        "recommendations": recommendations,
        "should_continue": should_continue,
        # The measured inputs the judgement was made against (never model output).
        "metrics": {k: (performance or {}).get(k) for k, _, _ in _METRIC_LABELS
                    if (performance or {}).get(k) is not None},
        "evaluated_at": datetime.utcnow().isoformat(),
    }


# ======================= Art Director Agent (ads-image) ====================

# Rendering an image is a media-model call, not a language-model one, so it stays
# in the backend. Everything that needs judgement about the picture - what the
# scene is, the composition, the lighting, which of the business's real photos to
# keep - is this agent's job. It is the only writer of image prompts.
IMAGE_AGENT_PROMPT = """You are the Art Director for one small business's paid social ads.

You run as the dedicated OpenClaw ads-image agent. You are given the business's own facts
(name, what it sells, description, brand colours, the owner's creative direction), the ad
copy or campaign the image has to serve, and - when the business has them - its real logo,
uploaded photos and website screenshot as numbered reference images you can see.

Write the prompt a photorealistic image model needs to produce ONE finished ad image, and say
which reference images it should keep. The image model has no other context: everything it can
know about this business is what you put in the prompt.

Rules:
1. Give a brief a photographer could shoot: subject, action, setting, composition, lighting,
   mood, colour and how the product is shown. Be specific to THIS business and what it sells.
2. Use only the facts you were given. Never invent a product, location, claim, price, phone
   number, or brand name that is not in the input.
3. Reference images are the business's real appearance. When you use them, say in the prompt to
   keep the logo, uniforms, vehicles, products and premises faithful to them - never redesign or
   reinterpret them. Do not reference an image that is unrelated to this scene.
4. Image models render text badly. Ask for text only when the ad genuinely needs a headline,
   and then specify the exact string; otherwise ask for no text at all.
5. Pick the approach that fits the objective and the business: a lifestyle moment for an
   emotional angle, a product-led studio composition for a retail product, a contrast for a
   problem/solution angle. Do not default to stock-photo people at laptops unless that really
   is this business.
6. With no usable photos, work from the facts and describe the real thing it sells (a real
   laptop, a real meal, a real storefront) rather than an abstract generic scene.

Return ONLY JSON, no prose and no code fence:
{"prompt": "the full image prompt, one paragraph", "reference_numbers": [<numbers from the
reference list, in the order they should be attached>], "reasoning": "one sentence on the art
direction and why"}
"""

IMAGE_SET_AGENT_PROMPT = """You are the Art Director for one small business's paid social campaign.

You run as the dedicated OpenClaw ads-image agent. One campaign has several copy variations,
and each needs its OWN image that visualises that variation's angle - not the same picture
re-captioned. You are given the business's facts, every copy variation that needs a creative,
and the candidate photos from the business's own website as numbered reference images you can
see.

For each variation, pick the photos that genuinely show what the ad must copy (staff in their
real uniforms, branded vehicles, the real products, the premises) and write the prompt a
photorealistic image model needs. The image model has no other context than your prompt.

Rules:
1. Every variation gets its own prompt, visibly different in scene and composition from the
   others. Match the variation's angle and the approach it names.
2. Use only the business facts you were given. Never invent a product, claim, price, phone
   number or brand name that is not in the input.
3. Photos you pick are the business's real appearance: say in the prompt to copy the same
   uniforms, vehicles, products and premises exactly, and never invent new ones. Only pick
   photos that fit that variation's scene; pick none when none fit.
4. Text renders badly: ask for text only when the ad needs a headline or call to action, and
   then quote the exact string. Otherwise ask for no text.
5. Product-led variations run without people (the product is the hero); emotional ones may
   show one clear subject with a genuine expression, not staged stock models.
6. Describe the real thing the business sells, never an abstract generic scene.

Return ONLY JSON, no prose and no code fence:
{"prompts": [{"index": <variation index>, "prompt": "...", "photos": [<photo numbers>],
"use_screenshot": true}]}
Every variation index must appear exactly once.
"""


def _json_block(value: Any, limit: int = 6000) -> str:
    """Compact JSON for an agent turn, with empty fields dropped."""
    if isinstance(value, dict):
        value = {k: v for k, v in value.items() if v not in (None, "", [], {})}
    try:
        return json.dumps(value, indent=2, default=str)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def _clean_references(references: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [r for r in (references or []) if isinstance(r, dict) and r.get("url")]


def _image_direction_prompt(context: Dict[str, Any], references: List[Dict[str, Any]]) -> str:
    ref_lines = [f"{i}. {r.get('kind') or 'image'}" for i, r in enumerate(references, 1)]
    return (
        "## Business and brief\n"
        + _json_block(context)
        + "\n\n## Reference images available (use only these numbers)\n"
        + ("\n".join(ref_lines) if ref_lines else "none - the business has no usable images")
        + "\n\nWrite the art direction for one ad image for this business."
    )


def _validate_image_direction(raw: Any, references: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Strict check of one art-direction answer. Raises instead of guessing a prompt."""
    if not isinstance(raw, dict):
        raise gateway.output_error("image", "expected a JSON art-direction object")
    text = " ".join(str(raw.get("prompt") or "").split())
    if len(text) < 40:
        raise gateway.output_error("image", "the image prompt was empty or too thin to render")
    indices: List[int] = []
    if raw.get("use_reference_images") is not False:
        for item in raw.get("reference_numbers") or []:
            number = _num(item)
            if number is None or not number.is_integer():
                continue
            number = int(number)
            if 1 <= number <= len(references) and number not in indices:
                indices.append(number)
    return {
        "prompt": text,
        "reference_indices": indices,
        "reasoning": str(raw.get("reasoning") or "").strip(),
    }


async def art_direct_image(
    context: Dict[str, Any],
    references: Optional[List[Dict[str, Any]]] = None,
    store_id: str = "",
) -> Dict[str, Any]:
    """Ask the ads-image agent for one ad image's art direction.

    `references` are the business's real images, in order: [{"url", "kind"}, ...].
    Returns {"prompt": str, "reference_indices": [1-based ints], "reasoning": str}.
    Raises 503/502 when the gateway cannot give a real prompt - there is no
    hardcoded template to fall back to.
    """
    references = _clean_references(references)
    raw = await gateway.ask_json(
        "image", _session_key("image", store_id), IMAGE_AGENT_PROMPT,
        _image_direction_prompt(context, references), expect="object", timeout=180.0,
    )
    return _validate_image_direction(raw, references)


def art_direct_image_sync(
    context: Dict[str, Any],
    references: Optional[List[Dict[str, Any]]] = None,
    store_id: str = "",
) -> Dict[str, Any]:
    """Blocking art direction for callers outside the event loop (assets/campaigns)."""
    references = _clean_references(references)
    raw = gateway.ask_json_sync(
        "image", _session_key("image", store_id), IMAGE_AGENT_PROMPT,
        _image_direction_prompt(context, references), expect="object", timeout=180.0,
    )
    return _validate_image_direction(raw, references)


def _image_set_inputs(
    variations: List[Dict[str, Any]],
    photos: Optional[List[Dict[str, Any]]],
    thumbnails: Optional[List[str]],
) -> tuple:
    variations = [v for v in (variations or []) if isinstance(v, dict) and isinstance(v.get("index"), int)]
    photos = [p for p in (photos or []) if isinstance(p, dict) and p.get("url")]
    thumbnails = [t for t in (thumbnails or []) if t][:len(photos)]
    return variations, photos, thumbnails


def _image_set_prompt(context: Dict[str, Any], variations: List[Dict[str, Any]],
                      photos: List[Dict[str, Any]]) -> str:
    photo_lines = [f"{i}. {p.get('kind') or 'website photo'}" for i, p in enumerate(photos, 1)]
    return (
        "## Business and campaign\n"
        + _json_block(context)
        + "\n\n## Copy variations needing an image\n"
        + _json_block(variations, limit=9000)
        + "\n\n## Candidate photos from the business's own website (attached in this order)\n"
        + ("\n".join(photo_lines) if photo_lines else "none")
        + "\n\nWrite one art direction per variation."
    )


def _validate_image_set(raw: Any, variations: List[Dict[str, Any]],
                        photos: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Strict check of a campaign's art directions: every variation or an error."""
    if not isinstance(raw, dict):
        raise gateway.output_error("image", "expected a JSON object of image prompts")
    wanted = [v["index"] for v in variations]
    out: Dict[int, Dict[str, Any]] = {}
    for item in raw.get("prompts") or []:
        if not isinstance(item, dict):
            continue
        number = _num(item.get("index"))
        if number is None or not number.is_integer():
            continue
        index = int(number)
        text = " ".join(str(item.get("prompt") or "").split())
        if index not in wanted or index in out or len(text) < 40:
            continue
        picked: List[str] = []
        for value in item.get("photos") or []:
            photo_number = _num(value)
            if photo_number is None or not photo_number.is_integer():
                continue
            photo_number = int(photo_number)
            if 1 <= photo_number <= len(photos):
                url = photos[photo_number - 1]["url"]
                if url not in picked:
                    picked.append(url)
        out[index] = {
            "prompt": text,
            "photo_urls": picked,
            "use_screenshot": item.get("use_screenshot") is not False,
        }
    missing = [i for i in wanted if i not in out]
    if missing:
        raise gateway.output_error(
            "image", f"no usable art direction for variation(s) {', '.join(map(str, missing))}"
        )
    return out


async def art_direct_image_set(
    context: Dict[str, Any],
    variations: List[Dict[str, Any]],
    photos: Optional[List[Dict[str, Any]]] = None,
    thumbnails: Optional[List[str]] = None,
    store_id: str = "",
) -> Dict[int, Dict[str, Any]]:
    """Art direction for every creative in one campaign, in a single agent turn.

    `photos` are the candidate photos the business's site actually publishes, in the
    same order as `thumbnails` (data URIs the agent can see). Returns
    {variation_index: {"prompt", "photo_urls", "use_screenshot"}}; every variation
    must get a prompt or the whole call fails, because a campaign that silently loses
    a creative is worse than a visible error.
    """
    variations, photos, thumbnails = _image_set_inputs(variations, photos, thumbnails)
    raw = await gateway.ask_json(
        "image", _session_key("image", store_id), IMAGE_SET_AGENT_PROMPT,
        _image_set_prompt(context, variations, photos), expect="object",
        timeout=240.0, images=thumbnails or None,
    )
    return _validate_image_set(raw, variations, photos)


def art_direct_image_set_sync(
    context: Dict[str, Any],
    variations: List[Dict[str, Any]],
    photos: Optional[List[Dict[str, Any]]] = None,
    thumbnails: Optional[List[str]] = None,
    store_id: str = "",
) -> Dict[int, Dict[str, Any]]:
    """Blocking variant for the campaign creative builder."""
    variations, photos, thumbnails = _image_set_inputs(variations, photos, thumbnails)
    raw = gateway.ask_json_sync(
        "image", _session_key("image", store_id), IMAGE_SET_AGENT_PROMPT,
        _image_set_prompt(context, variations, photos), expect="object",
        timeout=240.0, images=thumbnails or None,
    )
    return _validate_image_set(raw, variations, photos)
