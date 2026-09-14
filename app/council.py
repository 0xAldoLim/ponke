import asyncio
import json

import structlog
from sqlalchemy import select

from app.database import AgentOpinion, Decision, DecisionOutcome
from app.schemas import Opinion, Verdict
from app.validation import Clarification

log = structlog.get_logger()
ROLES = {
    "macro": "Macro Opportunity: seek asymmetric upside, liquidity, rates, USD, BTC cycles, Indonesian and global macro, capital rotation. Distinguish supplied evidence from speculation; no current market feed is connected.",
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


class Council:
    def __init__(self, model):
        self.model = model

    async def run(self, question, context):
        async def specialist(role, prior=None):
            log.info("agent_invoked", agent=role, round=2 if prior else 1)
            instruction = (
                "Act as the functional specialist "
                + ROLES[role]
                + " You are not a real person or an impersonation. Return concise argument summaries. "
                "Use only supplied facts; missing information must constrain confidence. "
            )
            if prior is not None:
                instruction += (
                    "Round 2: independently review ALL round 1 opinions. Identify the strongest opposing "
                    "argument, overlooked information, whether your position changed, and update confidence and action."
                )
            else:
                instruction += "Round 1: analyze independently. Set strongest_opposing_argument null and changed_position false."
            result = await self.model.structured(
                Opinion, instruction, {"question": question, "context": context, "round_1": prior}
            )
            return Opinion.model_validate(result.model_dump())

        first_values = await asyncio.gather(*(specialist(role) for role in ROLES))
        first = {role: opinion.model_dump() for role, opinion in zip(ROLES, first_values, strict=True)}
        second_values = await asyncio.gather(*(specialist(role, first) for role in ROLES))
        second = {role: opinion.model_dump() for role, opinion in zip(ROLES, second_values, strict=True)}
        log.info("agent_invoked", agent="chief_analyst")
        verdict = await self.model.structured(
            Verdict,
            "Act as Chief Analyst. Synthesize the two specialist rounds without simply averaging scores. "
            "Determine decision type and context-dependent relevance weights summing to 100. "
            "Investment should emphasize risk and macro; purchases utility and affordability; medical decisions health. "
            "Evaluate evidence quality and disagreement. Separate facts, assumptions, missing evidence. "
            "Unknown liquidity, debt or current evidence must prevent claims of affordability or current market opportunity. "
            "Use NEED INFORMATION when critical evidence is missing. No historical automatic weight adjustment.",
            {"question": question, "context": context, "round_1": first, "round_2": second},
        )
        verdict = Verdict.model_validate(verdict.model_dump())
        return verdict, first, second

    async def persist(self, db, user_id, question, context, result):
        verdict, first, second = result
        decision = Decision(
            user_id=user_id,
            user_question=question,
            decision_type=verdict.decision_type,
            context_snapshot=json.loads(json.dumps(context, default=str)),
            final_recommendation=verdict.model_dump(),
            final_confidence=verdict.confidence,
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
                        confidence=opinion["confidence"],
                        score=opinion["score"],
                        summarized_reasoning=opinion,
                        recommended_action=opinion["recommended_action"],
                    )
                )
        return decision


def render_verdict(verdict, second=None):
    if isinstance(verdict, dict):
        verdict = Verdict.model_validate(verdict)
    text = f"DECISION: {verdict.decision}\nConfidence: {verdict.confidence}/100\n\n{verdict.recommended_action}\n\nWhy:\n"
    text += "\n".join("• " + reason for reason in verdict.reasons[:4])
    if second:
        text += "\n\nCouncil:\n" + "\n".join(
            f"{LABELS[role]}: {opinion['score']}/100 ({opinion['position']})"
            for role, opinion in second.items()
        )
    text += "\n\nMain disagreement:\n" + verdict.main_disagreement
    text += "\n\nWhat would change this:\n" + "\n".join("• " + item for item in verdict.what_would_change[:3])
    if verdict.missing_evidence:
        text += "\n\nMissing evidence: " + "; ".join(verdict.missing_evidence[:3])
    return text + "\n\nSend “details” for the full argument summaries."


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
            await db.scalars(
                select(AgentOpinion).where(AgentOpinion.decision_id == decision.id, AgentOpinion.round == 2)
            )
        ).all()
        text = render_verdict(decision.final_recommendation)
        text += "\n\nRelevance: " + decision.final_recommendation["relevance_explanation"]
        for opinion in opinions:
            text += (
                f"\n\n{LABELS[opinion.agent_name]}\n{opinion.summarized_reasoning['key_argument']}\nRisks: "
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
    db.add(
        DecisionOutcome(
            user_id=user_id,
            decision_id=decision.id,
            outcome_description=e.description,
            user_satisfaction=e.satisfaction,
        )
    )
    decision.status = "reviewed"
    return "Recorded the outcome. Council calibration remains informational until enough outcomes exist."
