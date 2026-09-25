import asyncio
import json
import re

import structlog
from sqlalchemy import select

from app.database import AgentOpinion, Decision, DecisionOutcome
from app.schemas import DecisionSynthesis, SpecialistView
from app.validation import Clarification, money

log = structlog.get_logger()
ROLES = {
    "macro": "Macro Opportunity: seek asymmetric upside, liquidity, rates, USD, BTC cycles, Indonesian and global macro, capital rotation. Distinguish supplied timestamped market evidence from speculation; feeds may be stale or unavailable.",
    "risk": "Risk & Portfolio: challenge assumptions, diversification, debt cycles, concentration, drawdowns, correlations, scenario probabilities and tail risk. What if the primary assumption is wrong?",
    "lifestyle": "Lifestyle Utility: weigh value per use, actual usefulness, happiness, impulse spending, lifestyle inflation, urgency and opportunity cost. Discretionary spending can be worthwhile.",
    "health": "Health Reality: evaluate sleep, exercise, recovery, supplements, physical risk and wellbeing. Be conservative on medical topics and recommend qualified care where relevant. Never diagnose.",
}
LABELS = {
    "macro": "Macro Opportunity",
    "risk": "Risk & Portfolio",
    "lifestyle": "Lifestyle Utility",
    "health": "Health Reality",
}
ROLE_SETS = {
    "health": ("health",),
    "investment": ("macro", "risk"),
    "purchase": ("lifestyle", "risk"),
    "career": ("lifestyle", "risk"),
    "other": ("lifestyle", "risk"),
}


def relevant_roles(decision_type, question):
    if decision_type == "health":
        return ROLE_SETS["health"]
    if decision_type == "investment":
        return ROLE_SETS["investment"]
    topic = question.casefold()
    if re.search(
        r"\b(?:crypto|cryptocurrency|bitcoin|btc|invest(?:ing|ment|ments)?|economy|economic|markets?|stocks?|shares?)\b",
        topic,
    ):
        return ROLE_SETS["investment"]
    if decision_type in ROLE_SETS and decision_type != "other":
        return ROLE_SETS[decision_type]
    if re.search(r"\b(?:health|medical|symptoms?|supplements?|sleep)\b", topic):
        return ROLE_SETS["health"]
    return ROLE_SETS["other"]


def deep_roles(decision_type, question):
    roles = list(relevant_roles(decision_type, question))
    topic = question.casefold()
    for role, pattern in (
        ("macro", r"\b(?:economy|market|investment|stock|crypto|interest rate)\b"),
        ("risk", r"\b(?:risk|debt|portfolio|afford|investment|buy)\b"),
        ("lifestyle", r"\b(?:lifestyle|career|car|house|purchase|family)\b"),
        ("health", r"\b(?:health|medical|sleep|fitness|injury)\b"),
    ):
        if role not in roles and re.search(pattern, topic):
            roles.append(role)
    return tuple(roles[:4])


class Council:
    def __init__(self, model):
        self.model = model

    async def run(self, question, context, decision_type=None, depth="fast"):
        roles = (
            deep_roles(decision_type, question)
            if depth == "deep"
            else relevant_roles(decision_type, question)
        )

        if len(roles) == 1:
            role = roles[0]
            log.info("agent_invoked", agent=role, round=1)
            verdict = await self.model.structured(
                DecisionSynthesis,
                "Act only as this functional specialist: "
                + ROLES[role]
                + " Give a careful, concise decision from the supplied evidence. "
                + context.get("voice_instruction", "")
                + " "
                "Do not imply other specialists were consulted. Do not output numerical scores in prose. "
                "Write recommended_action as Ponke speaking directly to the user in one or two short "
                "natural sentences. Set common_ground empty. "
                "Set main_disagreement to an empty string because only one specialist is relevant. "
                "Name critical missing evidence; do not invent current prices or medical facts.",
                {"question": question, "context": context},
            )
            return DecisionSynthesis.model_validate(verdict.model_dump()), {}, {}

        async def specialist(role):
            log.info("agent_invoked", agent=role, round=1)
            instruction = (
                "Act as the functional specialist "
                + ROLES[role]
                + " You are not a real person or an impersonation. Return concise argument summaries. "
                "Use only supplied facts; missing information must constrain confidence. "
                "Analyze independently. Give your strongest argument and the main risks."
            )
            result = await self.model.structured(
                SpecialistView, instruction, {"question": question, "context": context}
            )
            return SpecialistView.model_validate(result.model_dump())

        first_values = await asyncio.gather(*(specialist(role) for role in roles))
        first = {role: opinion.model_dump() for role, opinion in zip(roles, first_values, strict=True)}
        second = {}
        if depth == "deep" and len(roles) > 1:

            async def cross_review(role):
                log.info("agent_invoked", agent=role, round=2)
                others = {name: view for name, view in first.items() if name != role}
                return await self.model.structured(
                    SpecialistView,
                    "Cross-review the other relevant arguments once. Revise your position only when evidence warrants it. Summarize the strongest unresolved point; no scores or theatrical debate. "
                    + ROLES[role],
                    {
                        "question": question,
                        "context": context,
                        "own_argument": first[role],
                        "other_arguments": others,
                    },
                )

            second_values = await asyncio.gather(*(cross_review(role) for role in roles))
            second = {
                role: SpecialistView.model_validate(value.model_dump()).model_dump()
                for role, value in zip(roles, second_values, strict=True)
            }
        log.info("agent_invoked", agent="chief_analyst")
        verdict = await self.model.structured(
            DecisionSynthesis,
            "Act as Chief Analyst. Synthesize only the selected specialists' arguments. "
            + context.get("voice_instruction", "")
            + " "
            "Compare evidence, assumptions and practical consequences. "
            "Write as Ponke speaking directly to the user in plain, concise language. "
            "Keep the total reply under about 75 words. Answer the question first in recommended_action. "
            "In common_ground, give one short point "
            "supported by both arguments. In main_disagreement, contrast the strongest upside and "
            "risk arguments only if they genuinely differ; otherwise leave it empty. "
            "Avoid report language such as 'the user', 'the macro specialist', 'both specialists', "
            "'perspectives', 'parameters', 'fully defined', headings or numbered scores. "
            "Do not refer to the people or process behind the analysis; say 'the upside' or 'the risk' instead. "
            "Do not repeat the same point. A natural style sounds like: "
            "'That could work if it fits your budget. The upside is real, but the downside could hurt. "
            "I'd want to know your timeline before saying yes.' "
            "Write missing_evidence as short phrases addressed to the user, such as 'your time horizon' "
            "or 'your cash buffer', and include only the most decision-relevant gaps. "
            "For a broad question, give a conditional educational answer instead of requiring a "
            "personalized yes/no. Use NEED INFORMATION only when a personalized decision cannot be "
            "made responsibly from the supplied evidence. "
            "Do not invent disagreement or consensus. "
            "Separate facts, assumptions and missing evidence. "
            "Unknown liquidity or debt must prevent a personalized affordability claim. "
            "Do not claim to know current market prices or conditions without supplied evidence. "
            "Use NEED INFORMATION when critical evidence is missing.",
            {
                "question": question,
                "context": context,
                "arguments": list(second.values()) if second else list(first.values()),
            },
        )
        verdict = DecisionSynthesis.model_validate(verdict.model_dump())
        return verdict, first, second

    async def persist(self, db, user_id, question, context, result):
        verdict, first, second = result
        decision = Decision(
            user_id=user_id,
            user_question=question,
            decision_type=verdict.decision_type,
            context_snapshot=json.loads(json.dumps(context, default=str)),
            final_recommendation=verdict.model_dump(),
            final_confidence=0,  # Legacy non-null column; no numerical confidence is inferred.
        )
        db.add(decision)
        await db.flush()
        for round_number, opinions in ((1, first), (2, second)):
            for role, opinion in opinions.items():
                db.add(
                    AgentOpinion(
                        decision_id=decision.id,
                        agent_name=role,
                        round=round_number,
                        position=opinion["position"],
                        confidence=0,
                        score=0,  # Legacy non-null columns, excluded from new model output.
                        summarized_reasoning=opinion,
                        recommended_action=opinion["recommended_action"],
                    )
                )
        return decision


def render_verdict(verdict):
    if isinstance(verdict, dict):
        fields = {key: verdict[key] for key in DecisionSynthesis.model_fields if key in verdict}
        fields.setdefault("common_ground", "")  # Existing decisions predate the new reply field.
        verdict = DecisionSynthesis.model_validate(fields)
    parts = [verdict.recommended_action.strip()]
    common = verdict.common_ground.strip()
    if common and common.casefold() not in parts[0].casefold():
        parts.append(common)
    disagreement = verdict.main_disagreement.strip()
    if disagreement and disagreement.casefold() not in {"none", "no disagreement", "n/a"}:
        parts.append(disagreement)
    if verdict.decision == "NEED INFORMATION" and verdict.missing_evidence:
        missing = ", ".join(
            item.strip().removeprefix("User's ").removeprefix("user's ")
            for item in verdict.missing_evidence[:2]
        )
        missing = missing[:1].lower() + missing[1:]
        if missing.casefold() not in " ".join(parts).casefold():
            parts.append("I'd need " + missing + " to make this more specific.")
    return " ".join(part for part in parts if part)


async def history(db, user_id, search=None, details=False):
    statement = select(Decision).where(Decision.user_id == user_id)
    if search:
        statement = statement.where(Decision.user_question.icontains(search, autoescape=True))
    decisions = list((await db.scalars(statement.order_by(Decision.created_at.desc()).limit(10))).all())
    if not decisions:
        return "No matching decisions have been recorded."
    if details:
        decision = decisions[0]
        opinions = (
            await db.scalars(select(AgentOpinion).where(AgentOpinion.decision_id == decision.id))
        ).all()
        latest = {opinion.agent_name: opinion for opinion in sorted(opinions, key=lambda item: item.round)}
        text = render_verdict(decision.final_recommendation)
        for opinion in latest.values():
            text += (
                f"\n\n{LABELS[opinion.agent_name]}: {opinion.summarized_reasoning['key_argument']}\nRisks: "
                + "; ".join(opinion.summarized_reasoning["risks"])
            )
        return text
    return "\n\n".join(
        f"{d.id}\n{d.created_at:%Y-%m-%d} — {d.user_question}\n{d.final_recommendation['recommended_action']}"
        for d in decisions
    )


async def record_outcome(db, user_id, e):
    decision = await db.scalar(
        select(Decision).where(Decision.user_id == user_id, Decision.id == e.target_id)
    )
    if not decision or not e.description:
        raise Clarification("Please identify the decision and describe what happened.")
    result = None
    if e.result_amount:
        if not e.currency:
            raise Clarification("Include the currency for a measurable financial outcome.")
        negative = e.result_amount.strip().startswith("-")
        result = money(e.result_amount.strip().lstrip("-"), e.currency)
        if negative:
            result = -result
    db.add(
        DecisionOutcome(
            user_id=user_id,
            decision_id=decision.id,
            outcome_description=e.description,
            user_action=e.actual_action[:250] if e.actual_action else None,
            measurable_result=result,
            result_currency=e.currency.upper() if result is not None else None,
            user_satisfaction=e.satisfaction,
        )
    )
    decision.status = "reviewed"
    decision.follow_up_date = None
    return "Recorded the outcome. Council calibration remains informational until enough outcomes exist."
