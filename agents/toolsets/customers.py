"""Customer management and lookup toolset.

All tools are prefixed with 'customers_' to prevent naming collisions.
"""

from pydantic_ai import FunctionToolset, RunContext

from agents.deps import AgentDeps
from db.queries.customer import find_customer_by_contact

# Create toolset
customers_toolset = FunctionToolset()


@customers_toolset.tool
async def lookup(
    ctx: RunContext[AgentDeps],
    email: str | None = None,
    phone: str | None = None,
) -> str:
    """Find and retrieve customer information by their contact details.

    Operation: READ (Simple GET)
    Customer Interaction: No

    Use this tool when:
    - A customer contacts you and you need to look up their profile
    - You need to check their order history or preferences
    - You want to see if they're a VIP or have special tags

    Do NOT use if:
    - You already have the customer information in the conversation context
    - Neither email nor phone number is provided

    Args:
        email: Customer's email address (optional)
        phone: Customer's phone number (optional)

    Returns:
        Customer profile information in natural language format, or a message
        indicating this is a new customer.

    Important:
    - At least one of email or phone must be provided
    - Returns formatted customer details including tags, lifecycle stage, and notes
    - If no customer found, indicates this is a new customer
    """
    if not email and not phone:
        return (
            "Error: Please provide either an email address or phone number to look up the customer."
        )

    customer = await find_customer_by_contact(ctx.deps.business_id, email=email, phone=phone)

    if not customer:
        return (
            "Customer not found in our system. This appears to be a new customer. "
            "You can assist them with product inquiries or help them create an order."
        )

    # Format response in natural language
    contact_info = customer.email or customer.phone or "No contact info"
    tags_str = ", ".join(customer.tags) if customer.tags else "None"
    value_score = (
        f"{customer.customer_value_score}/100" if customer.customer_value_score else "Not scored"
    )

    return f"""Customer Profile:
Name: {customer.name or "Not provided"}
Contact: {contact_info}
Status: {customer.lifecycle_stage or "New customer"}
Tags: {tags_str}
Customer Value Score: {value_score}
Segments: {", ".join(customer.segments) if customer.segments else "None"}
Notes: {customer.notes or "No notes on file"}

Use this information to provide personalized service."""
