from enum import Enum
import json
import os
from pydantic import BaseModel, Field
import openai
from typing import List
from dotenv import load_dotenv

from backend.db.db_utils import get_products

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI()

MODEL = "gpt-4o-mini"

UPSELLING_SYSTEM_PROMPT = """
You're an AI upselling assistant. After a customer's purchase or inquiry:

1. Identify complementary products.
2. Suggest these items, emphasizing benefits and compatibility.
3. Use persuasive language, but respect customer preferences.
4. Offer bundle deals or discounts when appropriate.
5. Adapt recommendations based on customer responses.
6. Aim to enhance customer's experience and increase sales.
7. Be friendly, knowledgeable, and focused on customer satisfaction.

These tools are available for you to use. Invoke them when needed:
- GetRelatedProducts: Use to determine products similar, related or could go along with the recently purchased product.
- Product: Use to get price, available and information about a product.
"""


class Product(BaseModel):
    """
    Use to find a product based on user query
    """

    name: str = Field(description="The name of the product")

    async def execute(
        self,
    ):  # add context/intent and based on it, the prompt varies e.g customer bought, customer requested for etc.
        search_terms = await get_products(name=self.name)
        results = (
            search_terms  # todo: add a function that looks up db with search terms
        )
        return results


instructions = {
    "purchased": "This item was purchased. Suggest only complementary products that can be used alongside the bought product(s).",
    "inquired": "This item was inquired but not available. Suggest only direct/complete alternative products to buy.",
}


class Instruction(str, Enum):
    purchased = "purchased"
    inquired = "inquired"


class ProductLists(BaseModel):
    """
    Use to determine products related or could be used
    or purchased alongside with the recently purchased or inquired product.
    """

    products: List[Product] = Field(description="List of products")


class GetRelatedProducts(BaseModel):
    """
    Use to determine the product similar to recently purchased or inquired product.
    """

    product: str
    instruction: Instruction  # = Field(description="Intent of purchase, either 'purchased' or 'inquired'")

    async def execute(
        self,
    ):  # add context/intent and based on it, the prompt varies e.g customer bought, customer requested for etc.
        completion = get_parsed_completion(
            ProductLists,
            [
                {"role": "system", "content": instructions[self.instruction]},
                {"role": "user", "content": f"Product is {self.product}"},
            ],
        )
        results = ProductLists.model_validate_json(completion)
        print(results, "\n\n")
        search_terms = [await get_products(name=p.name) for p in results.products]
        results = (
            search_terms  # todo: add a function that looks up db with search terms
        )
        return results


TOOLS = [
    openai.pydantic_function_tool(GetRelatedProducts),
    openai.pydantic_function_tool(Product),
]

TOOLS_MAP = {
    "GetRelatedProducts": GetRelatedProducts,
    "Product": Product,
}


def get_parsed_completion(model: BaseModel, messages: list):
    completion = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=messages,
        response_format=model,
    )

    return completion.choices[0].message.content


async def execute_tool(tool_calls, messages):

    for tool_call in tool_calls:
        tool_name = tool_call.function.name
        tool_arguments = json.loads(tool_call.function.arguments)
        tool_call_id = tool_call.id
        output = await TOOLS_MAP[tool_name](**tool_arguments).execute()
        messages.append(
            {
                "role": "tool",
                "name": tool_name,
                "tool_call_id": tool_call_id,
                "content": json.dumps(output),
            }
        )

    return messages


async def run_upselling_agent(product_name, product_category, instruction, conversation_messages=[]):
    user_message = {"role": "assistant", "content": f"Product: {product_name}, Product_category: {product_category}, Instruction: {instruction}"}
    conversation_messages.append(user_message)
    
    messages = [{"role": "system", "content": UPSELLING_SYSTEM_PROMPT}]
    messages.extend(conversation_messages)

    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            tools=TOOLS,
        )

        if response.choices[0].message.tool_calls:
            conversation_messages.extend([response.choices[0].message])
            messages = await execute_tool(
                response.choices[0].message.tool_calls, conversation_messages
            )
        else:
            return response.choices[0].message.content


if __name__ == "__main__":
    import asyncio

    async def main():
        print(await run_upselling_agent("Oxford shoes size 38", "purchased"))

    asyncio.run(main())
