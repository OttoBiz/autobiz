"""
LLM actor agents used to simulate customers, vendors, logistics operators, and a judge.

These run locally (outside Docker) and interact with the deployed app through HTTP.
Set TEST_MODEL env var to override the default model.
Requires the appropriate API key for the chosen model.
"""
import os
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage

TEST_MODEL: str = os.environ.get("TEST_MODEL", "openai:gpt-4o")


# ── Output schemas ─────────────────────────────────────────────────────────────


class CustomerReply(BaseModel):
    message: str = Field(description="What the customer says next.")
    done: bool = Field(
        description="True when the customer is fully satisfied and wrapping up. False otherwise."
    )
    upload_receipt: bool = Field(
        default=False,
        description=(
            "Set True on the exact turn the customer should attach their payment receipt. "
            "Only set this once — after setting it, the receipt will be uploaded."
        ),
    )


class VendorReply(BaseModel):
    message: str = Field(description="What the vendor replies.")
    done: bool = Field(description="True when the vendor has no more to add.")


class LogisticsReply(BaseModel):
    message: str = Field(description="What the logistics operator replies.")
    done: bool = Field(description="True when the logistics operator is done.")


class JudgeVerdict(BaseModel):
    passed: bool = Field(description="True if all required criteria were met.")
    score: float = Field(description="Score from 0.0 (none met) to 1.0 (all met).")
    reason: str = Field(description="Concise explanation of the verdict.")
    found_criteria: list[str] = Field(description="Criteria that were clearly satisfied.")
    missing_criteria: list[str] = Field(description="Criteria that were not met.")


# ── Factory functions ──────────────────────────────────────────────────────────


def make_customer_agent(
    customer_name: str,
    business_name: str,
    scenario_prompt: str,
    model: str = TEST_MODEL,
) -> Agent:
    return Agent(
        model=model,
        output_type=CustomerReply,
        system_prompt=f"""You are {customer_name}, a customer chatting with {business_name} on WhatsApp.

{scenario_prompt}

RULES:
- Stay in character. Keep messages short and natural (1-3 sentences).
- Only set done=True AFTER your main goal is fully achieved and you are saying goodbye.
- Do NOT skip steps — follow your journey in order.
- Set upload_receipt=True ONLY on the turn you want to attach your payment receipt.""",
    )


def make_vendor_agent(
    vendor_name: str,
    inventory_description: str,
    payment_info: str,
    model: str = TEST_MODEL,
) -> Agent:
    return Agent(
        model=model,
        output_type=VendorReply,
        system_prompt=f"""You are the owner of {vendor_name}. An AI assistant contacts you on behalf of a customer.

YOUR INVENTORY:
{inventory_description}

PAYMENT INFO:
{payment_info}

RULES:
- Reply concisely and professionally (1-3 sentences).
- Provide honest stock info, pricing, and sourcing options when asked.
- Confirm logistics details when the system informs you of delivery arrangements.
- Set done=True when the conversation is concluded.""",
    )


def make_logistics_agent(
    company_name: str,
    service_description: str,
    model: str = TEST_MODEL,
) -> Agent:
    return Agent(
        model=model,
        output_type=LogisticsReply,
        system_prompt=f"""You are a representative of {company_name}, a logistics company.

{service_description}

RULES:
- Reply professionally and concisely.
- Confirm delivery timelines, costs, and pickup arrangements.
- Set done=True when the delivery arrangement is concluded.""",
    )


# ── Singleton judge ────────────────────────────────────────────────────────────

judge_agent = Agent(
    model=TEST_MODEL,
    output_type=JudgeVerdict,
    system_prompt="""You are a strict QA judge evaluating AI chatbot conversations for an e-commerce platform.

Your task: Read a conversation transcript and determine whether specific test criteria were satisfied.

RULES:
- Base your verdict ONLY on what is explicitly stated in the transcript.
- Do not infer things that were not clearly communicated.
- Each criterion either passed or failed — there is no partial credit per criterion.
- Score = (found_criteria count) / (total criteria count), rounded to 2 decimal places.
- If all criteria are found, score=1.0 and passed=True.
- If ANY criterion is missing, passed=False unless the score is > 0.7 and the missing items are minor.""",
)
