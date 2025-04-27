import os
from typing import List, Optional, Dict, Any, Type, Callable
from pydantic import BaseModel

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    PromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_openai import ChatOpenAI
from langchain.output_parsers.openai_functions import JsonOutputFunctionsParser

# Prompts
from ..prompts.central_agent_prompt import (
    customer_feedback_system_prompt,
    human_prompt,
    logistic_system_prompt,
    payment_verification_system_prompt,
    rule_system_prompt,
    unavailable_product_system_prompt,
)
from ..prompts.prompt import base_prompt, business_chat_prompt

# Agent Schemas and Tools
from .schema.business_function_args_schema import arg_schema as business_arg_schema
from .schema.user_function_args_schema import arg_schema as user_arg_schema
from .utils.central_agent import Response as CentralAgentResponse  # Renamed to avoid collision
from .upselling_agent import run_upselling_agent

# --- Configuration ---

# Load required environment variables
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Validate required configuration
if not MODEL_NAME:
    raise ValueError("Missing required environment variable: MODEL_NAME")
if not OPENAI_API_KEY:
    raise ValueError("Missing required environment variable: OPENAI_API_KEY")

# Supported Models (Expand if needed)
SUPPORTED_MODELS = {"gpt-3.5-turbo", "gpt-4", "gpt-4-turbo", "gpt-4o-mini", "gpt-4.1-mini"} # Add other supported GPT models


# --- Constants ---
DEFAULT_TEMPERATURE = 0.0
DEFAULT_STREAMING = False

TASK_LOGISTIC_PLANNING = "Logistic planning"
TASK_PAYMENT_VERIFICATION = "Payment verification"
TASK_CUSTOMER_FEEDBACK = "Customer Feedback"
TASK_PRODUCT_UNAVAILABLE = "Product Unavailable"

# --- Model Initialization ---

def initialize_model(
    model_name: str = MODEL_NAME,
    api_key: str = OPENAI_API_KEY,
    temperature: float = DEFAULT_TEMPERATURE,
    streaming: bool = DEFAULT_STREAMING,
    tools: Optional[List[Callable]] = None,
    structured_output_schema: Optional[Type[BaseModel]] = None,
) -> Runnable:
    """
    Initializes and configures a ChatOpenAI model instance.

    Args:
        model_name: The name of the OpenAI model to use.
        api_key: The OpenAI API key.
        temperature: The sampling temperature for the model.
        streaming: Whether to enable streaming responses.
        tools: A list of functions/tools to bind to the model.
        structured_output_schema: Pydantic model for structured output parsing.

    Returns:
        A configured LangChain Runnable.

    Raises:
        ValueError: If the model_name is not supported or required env vars are missing.
    """
    # Check if the model is supported (can be more specific if needed)
    # Basic check assuming all OpenAI models contain 'gpt' for now
    if "gpt" not in model_name.lower():
         # Or check against a predefined list: if model_name not in SUPPORTED_MODELS:
        raise ValueError(f"Unsupported model type: {model_name}. Only GPT models are currently supported.")

    # Initialize the core model
    model = ChatOpenAI(
        model=model_name,
        openai_api_key=api_key, # Explicitly pass API key
        temperature=temperature,
        streaming=streaming,
    )

    # Bind tools if provided
    if tools:
        openai_tools = [convert_to_openai_tool(func) for func in tools]
        model = model.bind(tools=openai_tools)

    # Apply structured output if schema is provided
    if structured_output_schema:
        # Ensure the schema is a Pydantic model
        if not issubclass(structured_output_schema, BaseModel):
             raise TypeError("structured_output_schema must be a Pydantic BaseModel")
        model = model.with_structured_output(structured_output_schema)

    return model


# --- Output Parsers ---
str_output_parser = StrOutputParser()
# Consider if this specific parser is still needed or if with_structured_output covers it
function_schema_parser = JsonOutputFunctionsParser()


# --- Prompt Templates ---

# Basic Prompts
business_prompt_template = PromptTemplate.from_template(business_chat_prompt)
user_prompt_template = PromptTemplate.from_template(base_prompt)

# Central Agent Task Prompts
logistic_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(logistic_system_prompt),
    HumanMessagePromptTemplate.from_template(human_prompt),
    SystemMessagePromptTemplate.from_template(rule_system_prompt),
])

customer_feedback_prompt = ChatPromptTemplate.from_messages([ # Renamed variable
    SystemMessagePromptTemplate.from_template(customer_feedback_system_prompt),
    HumanMessagePromptTemplate.from_template(human_prompt),
    SystemMessagePromptTemplate.from_template(rule_system_prompt),
])

unavailable_product_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(unavailable_product_system_prompt),
    HumanMessagePromptTemplate.from_template(human_prompt),
    SystemMessagePromptTemplate.from_template(rule_system_prompt),
])

payment_verification_prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(payment_verification_system_prompt),
    HumanMessagePromptTemplate.from_template(human_prompt),
    SystemMessagePromptTemplate.from_template(rule_system_prompt),
])


# --- Chain Definitions ---

# Business interface chain
business_chain = business_prompt_template | initialize_model(tools=business_arg_schema)

# User interface chain
user_chain = user_prompt_template | initialize_model(tools=user_arg_schema)

# Central agent base model (used by task-specific chains)
# Initialize with the specific tool and structured output needed for central agent tasks
central_llm = initialize_model(
    tools=[run_upselling_agent],
    structured_output_schema=CentralAgentResponse # Use the renamed schema
)

# Central agent chains mapped by task
central_agent_chains: Dict[str, Runnable] = {
    TASK_LOGISTIC_PLANNING: logistic_prompt | central_llm,
    TASK_PAYMENT_VERIFICATION: payment_verification_prompt | central_llm,
    TASK_CUSTOMER_FEEDBACK: customer_feedback_prompt | central_llm,
    TASK_PRODUCT_UNAVAILABLE: unavailable_product_prompt | central_llm,
}

# Agent responsible for fetching performance metrics and deriving insights for businesses.
# TODO: Implement the business_agent logic
business_agent: Optional[Runnable] = None # Define as None or implement