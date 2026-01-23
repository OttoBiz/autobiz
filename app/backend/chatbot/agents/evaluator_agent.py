"""
Evaluator Agent - Evaluates responses before sending to users
Ensures appropriateness and quality
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from .base_agent import BaseAgent


class EvaluationResult(BaseModel):
    """Evaluation result"""
    appropriate: bool = Field(..., description="Whether response is appropriate")
    score: float = Field(..., description="Quality score 0-10")
    feedback: str = Field(..., description="Feedback on the response")
    should_send: bool = Field(..., description="Whether to send the response")
    suggested_improvement: Optional[str] = Field(None, description="Suggested improvement")


class EvaluatorAgentDeps(BaseModel):
    """Dependencies for evaluator agent"""
    conversation_context: str
    api_key: Optional[str] = None


# Initialize evaluator agent
evaluator_agent_base = BaseAgent(
    system_prompt="""You are an evaluator agent that ensures responses are appropriate and high-quality.

**YOUR JOB**
- Evaluate responses before they are sent to users
- Check for appropriateness, tone, accuracy, and completeness
- Provide feedback and scores
- Suggest improvements if needed

**EVALUATION CRITERIA**
1. Appropriateness: Is the response suitable for the conversation context?
2. Tone: Is the tone professional and friendly?
3. Accuracy: Is the information correct?
4. Completeness: Does it address the user's question?
5. Clarity: Is it easy to understand?

**RULES**
- Score responses 0-10
- Only approve responses that score 7 or above
- Provide constructive feedback
- Be concise in your evaluation""",
    deps_type=EvaluatorAgentDeps,
    output_type=EvaluationResult
)

evaluator_agent = evaluator_agent_base.agent


async def evaluate_response(
    response: str,
    conversation_context: str,
    api_key: Optional[str] = None
) -> EvaluationResult:
    """
    Evaluate a response before sending to user.
    
    Args:
        response: Response to evaluate
        conversation_context: Context of the conversation
        api_key: Optional API key
        
    Returns:
        Evaluation result
    """
    deps = EvaluatorAgentDeps(
        conversation_context=conversation_context,
        api_key=api_key
    )
    
    prompt = f"""Evaluate this response:

Response: {response}

Conversation Context: {conversation_context}

Provide your evaluation."""
    
    result = await evaluator_agent.run(prompt, deps=deps)
    return result.output


async def should_send_response(
    response: str,
    conversation_context: str,
    api_key: Optional[str] = None
) -> bool:
    """Quick check if response should be sent"""
    evaluation = await evaluate_response(response, conversation_context, api_key)
    return evaluation.should_send and evaluation.score >= 7.0

