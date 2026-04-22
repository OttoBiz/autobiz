"""
Base Agent Class for Ottobiz
All agents inherit from this base class which provides common functionality.
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import logfire
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelRequest,
    SystemPromptPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from backend.config import config

logfire.configure(
    token=os.getenv("LOGFIRE_TOKEN"),
    send_to_logfire="if-token-present",
)
logfire.instrument_pydantic_ai()


@dataclass
class AgentDependencies:
    """Dependencies that can be passed to agents"""

    user_id: Optional[str] = None
    business_id: Optional[str] = None
    logistic_id: Optional[str] = None
    session_id: Optional[str] = None
    api_key: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


class BaseAgent:
    """
    Base agent class that all other agents inherit from.
    Provides model initialization and common agent functionality.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        instructions: Optional[str] = None,
        deps_type: Optional[type] = None,
        output_type: Optional[type] = None,
        tools: Optional[List[Any]] = None,
    ):
        """
        Initialize base agent with model selection.

        Args:
            model_name: Model name to use (defaults to config.MODEL_NAME)
            api_key: API key for the model (defaults to config.MODEL_API_KEY)
            system_prompt: System prompt for the agent
            instructions: Instructions for the agent
            deps_type: Type for dependencies
            output_type: Type for structured output (Pydantic model)
        """
        self.model_name = model_name or config.MODEL_NAME
        self.api_key = api_key or config.MODEL_API_KEY
        self.system_prompt = system_prompt
        self.instructions = instructions

        # Initialize model
        self.model = self._select_model(self.model_name, self.api_key)

        # Create agent with optional system prompt/instructions
        agent_kwargs = {}
        if system_prompt:
            agent_kwargs["system_prompt"] = system_prompt
        if instructions:
            agent_kwargs["instructions"] = instructions
        if deps_type:
            agent_kwargs["deps_type"] = deps_type
        if output_type:
            agent_kwargs["output_type"] = output_type
        if tools:
            agent_kwargs["tools"] = tools

        self.agent = Agent(self.model, **agent_kwargs)

    def _select_model(self, model_name: str, api_key: Optional[str] = None):
        """
        Select and initialize the appropriate model based on model_name.

        Accepts both bare model names (e.g. "gpt-4o") and pydantic-ai
        KnownModelName prefixed strings (e.g. "openai:gpt-4o", "google-gla:gemini-2.0-flash").
        The provider prefix is stripped before passing to the underlying model class.

        Args:
            model_name: Name of the model to use
            api_key: API key for the model

        Returns:
            Initialized model instance
        """
        api_key = api_key or config.MODEL_API_KEY

        # Strip provider prefixes used by pydantic-ai KnownModelName
        # e.g. "openai:gpt-4o" → "gpt-4o", "google-gla:gemini-2.0-flash" → "gemini-2.0-flash"
        bare_name = model_name.split(":", 1)[-1] if ":" in model_name else model_name

        if "gemini" in bare_name.lower():
            return GoogleModel(bare_name, provider=GoogleProvider(api_key=api_key))
        elif "claude" in bare_name.lower():
            return AnthropicModel(
                bare_name, provider=AnthropicProvider(api_key=api_key)
            )
        elif "gpt" in bare_name.lower() or "openai" in model_name.lower():
            return OpenAIModel(bare_name, provider=OpenAIProvider(api_key=api_key))
        else:
            # Default to Gemini
            return GoogleModel(bare_name, provider=GoogleProvider(api_key=api_key))

    async def run(
        self,
        prompt: str | List[Any],
        deps: Optional[Any] = None,
        message_history: Optional[List] = None,
        **kwargs,
    ):
        """
        Run the agent with a prompt.

        Args:
            prompt: User prompt or list of prompt parts
            deps: Dependencies to pass to the agent
            message_history: Previous message history
            **kwargs: Additional arguments

        Returns:
            Agent result
        """
        return await self.agent.run(
            prompt, deps=deps, message_history=message_history, **kwargs
        )

    def run_sync(
        self,
        prompt: str | List[Any],
        deps: Optional[Any] = None,
        message_history: Optional[List] = None,
        **kwargs,
    ):
        """
        Run the agent synchronously with a prompt.

        Args:
            prompt: User prompt or list of prompt parts
            deps: Dependencies to pass to the agent
            message_history: Previous message history
            **kwargs: Additional arguments

        Returns:
            Agent result
        """
        return self.agent.run_sync(
            prompt, deps=deps, message_history=message_history, **kwargs
        )

    def add_data(
        self,
        data: Union[List[Any], Dict[str, Any]],
        chat_history: Dict[Any, Any],
        **kwargs,
    ) -> str:
        context_parts = []

        # Get current datetime
        current_datetime = datetime.now()

        # Format date with ordinal suffix (1st, 2nd, 3rd, 4th, etc.)
        day = current_datetime.day
        if 10 <= day % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")

        # Format date: "Monday, 25th November 2025"
        month_names = [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
        day_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]
        day_of_week = day_names[current_datetime.weekday()]
        formatted_date = f"{day_of_week}, {day}{suffix} {month_names[current_datetime.month - 1]} {current_datetime.year}"

        # Format time in 12-hour format with am/pm: "8:30pm"
        hour = current_datetime.hour
        minute = current_datetime.minute
        if hour == 0:
            formatted_hour = 12
            period = "am"
        elif hour < 12:
            formatted_hour = hour
            period = "am"
        elif hour == 12:
            formatted_hour = 12
            period = "pm"
        else:
            formatted_hour = hour - 12
            period = "pm"

        formatted_time = f"{formatted_hour}:{minute:02d}{period}"

        # Add date and time to context
        context_parts.append(f"Today's Date: {formatted_date}")
        context_parts.append(f"Today's Time: {formatted_time}")

        # Add user information
        if data:
            context_parts.append(str(data))

        for key, value in kwargs.items():
            context_parts.append(f"{key.replace('_', ' ').title()}: {value}")
            # context_parts.append(f"{key.replace('_', ' ').title()}: {value}")

        if chat_history:
            chat_history[0].parts[0].content = f"{self.system_prompt}\n\n" + (
                "\n"
            ).join(context_parts)
        else:
            chat_history = [
                ModelRequest(
                    parts=[
                        SystemPromptPart(
                            content=f"{self.system_prompt}\n\n"
                            + ("\n").join(context_parts)
                        )
                    ]
                )
            ]

        return chat_history
