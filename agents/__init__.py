"""AI agents for customer service."""

# Import agent first
from agents.customer_agent import customer_agent

# Import tools to register them via decorators
# This must happen after agent import but before export
import agents.tools.conversations  # noqa: F401
import agents.tools.customers  # noqa: F401
import agents.tools.products  # noqa: F401

__all__ = ["customer_agent"]
