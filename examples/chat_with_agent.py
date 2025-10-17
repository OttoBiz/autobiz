"""Interactive chat script to test YAML-configured agents with MCP tools."""

import asyncio
from pathlib import Path

from agents.deps import AgentDeps
from agents.executor import AgentExecutor


# ANSI color codes for terminal output
class Colors:
    """Terminal color codes."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"


def print_system(message: str) -> None:
    """Print system message in dim gray."""
    print(f"{Colors.BRIGHT_BLACK}{message}{Colors.RESET}")


def print_success(message: str) -> None:
    """Print success message in green."""
    print(f"{Colors.GREEN}✓ {message}{Colors.RESET}")


def print_error(message: str) -> None:
    """Print error message in red."""
    print(f"{Colors.RED}❌ {message}{Colors.RESET}")


def print_user_prompt() -> str:
    """Print user prompt and get input in cyan."""
    return input(f"\n{Colors.BOLD}{Colors.CYAN}You:{Colors.RESET} ").strip()


def print_agent_label(agent_name: str) -> None:
    """Print agent label in magenta."""
    print(f"\n{Colors.BOLD}{Colors.MAGENTA}{agent_name}:{Colors.RESET} ", end="", flush=True)


def print_agent_message(message: str) -> None:
    """Print agent message content."""
    print(f"{Colors.MAGENTA}{message}{Colors.RESET}")


def print_header(message: str) -> None:
    """Print header in yellow."""
    print(f"{Colors.BOLD}{Colors.YELLOW}{message}{Colors.RESET}")


def print_separator() -> None:
    """Print separator line."""
    print(f"{Colors.BRIGHT_BLACK}{'─' * 60}{Colors.RESET}")


async def main():
    """Run interactive chat loop with agent."""

    # Initialize executor with MCP config
    print_system("\n🤖 Initializing AI Agent System...")
    mcp_config_path = Path("config/mcp_servers.json")
    from agents.registry import ToolsetManager

    toolset_manager = ToolsetManager(mcp_config_path=mcp_config_path)
    executor = AgentExecutor(toolset_manager=toolset_manager, model="openai:gpt-4o")

    # Load agents from YAML
    print_system("📂 Loading agents from YAML...")
    yaml_path = Path("config/agents/research_assistant.yaml")
    agents = await executor.load_agents_from_yaml(yaml_path)
    print_success(f"Loaded {len(agents)} agent(s): {[a.key for a in agents]}")

    # Create dependencies
    deps = AgentDeps(executor=executor, context_variables={})

    # Select agent
    agent_key = "researcher"
    print_separator()
    print_header(f"\n💬 Chat with {agents[0].name}")
    print_system("Type 'quit' or 'exit' to end the conversation")
    print_separator()

    # In-memory conversation (list of messages in Pydantic AI format)
    conversation = []

    # Interactive loop
    while True:
        # Get user input
        user_input = print_user_prompt()

        if not user_input:
            continue

        if user_input.lower() in ["quit", "exit"]:
            print_system("\n👋 Goodbye!\n")
            break

        try:
            # Run agent with in-memory conversation
            # The executor will automatically update the conversation list with new messages
            print_agent_label(agents[0].name)
            response = await executor.run(
                agent_key=agent_key,
                user_message=user_input,
                deps=deps,
                conversation=conversation,  # List is mutated in-place by executor
            )

            print_agent_message(response)

        except Exception as e:
            print_error(f"\nError: {e}")
            print_system("\nStack trace:")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
