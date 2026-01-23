"""
Base Agent Class for Ottobiz
All agents inherit from this base class which provides common functionality.
"""
from dataclasses import dataclass
from typing import Optional, Any, Dict, List
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.gemini import GeminiModel
from pydantic_ai.providers.google_gla import GoogleGLAProvider
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from backend.config import config


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
        deps_type: Optional[type] = None
    ):
        """
        Initialize base agent with model selection.
        
        Args:
            model_name: Model name to use (defaults to config.MODEL_NAME)
            api_key: API key for the model (defaults to config.MODEL_API_KEY)
            system_prompt: System prompt for the agent
            instructions: Instructions for the agent
            deps_type: Type for dependencies
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
            agent_kwargs['system_prompt'] = system_prompt
        if instructions:
            agent_kwargs['instructions'] = instructions
        if deps_type:
            agent_kwargs['deps_type'] = deps_type
            
        self.agent = Agent(self.model, **agent_kwargs)
    
    def _select_model(self, model_name: str, api_key: Optional[str] = None):
        """
        Select and initialize the appropriate model based on model_name.
        
        Args:
            model_name: Name of the model to use
            api_key: API key for the model
            
        Returns:
            Initialized model instance
        """
        api_key = api_key or config.MODEL_API_KEY
        
        if 'gemini' in model_name.lower():
            return GeminiModel(
                model_name,
                provider=GoogleGLAProvider(api_key=api_key)
            )
        elif 'claude' in model_name.lower():
            return AnthropicModel(
                'claude-3-5-sonnet-latest',
                provider=AnthropicProvider(api_key=api_key)
            )
        elif 'gpt' in model_name.lower() or 'openai' in model_name.lower():
            return OpenAIModel(
                'gpt-4o',
                provider=OpenAIProvider(api_key=api_key)
            )
        else:
            # Default to Gemini
            return GeminiModel(
                'gemini-2.0-flash',
                provider=GoogleGLAProvider(api_key=api_key)
            )
    
    async def run(
        self,
        prompt: str | List[Any],
        deps: Optional[Any] = None,
        message_history: Optional[List] = None,
        **kwargs
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
            prompt,
            deps=deps,
            message_history=message_history,
            **kwargs
        )
    
    def run_sync(
        self,
        prompt: str | List[Any],
        deps: Optional[Any] = None,
        message_history: Optional[List] = None,
        **kwargs
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
            prompt,
            deps=deps,
            message_history=message_history,
            **kwargs
        )


