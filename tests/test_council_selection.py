from app.council import relevant_roles
from app.schemas import DecisionSynthesis, SpecialistView


def test_relevant_roles_use_only_domains_that_fit():
    assert relevant_roles("health", "Should I take a supplement?") == ("health",)
    assert relevant_roles("investment", "Is crypto a good investment?") == ("macro", "risk")
    assert relevant_roles("purchase", "Should I buy a PC?") == ("lifestyle", "risk")
    assert relevant_roles("purchase", "Should I buy crypto?") == ("macro", "risk")
    assert relevant_roles("purchase", "Should I go to the supermarket?") == ("lifestyle", "risk")
    assert relevant_roles(None, "How would the economy affect my savings?") == ("macro", "risk")


async def test_health_decision_calls_only_health_specialist(env):
    _, _, model, _, service = env
    model.route("decision.request", decision_type="health")
    reply = await service.handle(123, "health-decision", "Should I take this supplement?")
    assert not [call for call in model.calls if call[0] is SpecialistView]
    final_calls = [call for call in model.calls if call[0] is DecisionSynthesis]
    assert len(final_calls) == 1
    assert "Health Reality" in final_calls[0][1]
    assert "Utility may justify" not in reply.text
    assert "50/100" not in reply.text


async def test_crypto_decision_calls_macro_and_risk_once_then_synthesizes(env):
    _, _, model, _, service = env
    model.route("decision.request", decision_type="investment")
    reply = await service.handle(123, "crypto-decision", "Is crypto a good investment?")
    opinions = [call for call in model.calls if call[0] is SpecialistView]
    final_calls = [call for call in model.calls if call[0] is DecisionSynthesis]
    assert len(opinions) == 2
    assert len(final_calls) == 1
    assert len(final_calls[0][2]["arguments"]) == 2
    assert "Affordability needs to be clear" in reply.text
    assert "50/100" not in reply.text

    model.route("decision.details")
    details = await service.handle(123, "crypto-details", "details")
    assert "Macro Opportunity" in details.text
    assert "Risk & Portfolio" in details.text
    assert "/100" not in details.text
