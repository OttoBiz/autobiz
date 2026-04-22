"""
Customer Complaint Agent - Handles customer complaints and feedback
"""

from backend.chatbot.agents.main_agent import AgentDeps

from .base_agent import BaseAgent

customer_complaint_agent_base = BaseAgent(
    system_prompt="""You are a customer service agent that handles customer complaints and feedback.

**YOUR JOB**
- Collect information about complaints/feedback and try to resolve issues.
- Refer customers to human agents when:
  - Issue is too complex
  - Customer demands refund
  - Product return or exchange is requested
  - Customer demands to speak with vendor directly

**OBJECTIVE**
- Resolve customer complaints efficiently.
- Escalate to human agents when necessary.""",
    deps_type=AgentDeps,
)

customer_complaint_agent = customer_complaint_agent_base.agent


async def run_customer_complaint_agent(
    customer_message: str,
    user_id: str,
    business_id: str,
    user_state: dict | None = None,
    **kwargs,
):
    """Legacy wrapper — delegates to customer_complaint_agent."""
    from backend.chatbot.agents.main_agent import AgentDeps

    deps = AgentDeps(user_id=user_id, business_id=business_id, state=user_state or {})
    result = await customer_complaint_agent.run(customer_message, deps=deps)
    return result.output, user_state or {}
