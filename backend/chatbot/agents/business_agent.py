from enum import Enum
import json
import os
from pydantic import BaseModel, Field
import openai
from typing import List, Dict, Optional, Union, Literal
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

client = openai.OpenAI()

MODEL = os.getenv("MODEL_NAME")

# Placeholder for database utility functions
async def get_products(name: str = None, category: str = None, in_stock: bool = None):
    """Placeholder: Get products from inventory database based on filters"""
    # This would be implemented to query your actual database
    return [{"id": "123", "name": "Sample Product", "price": 99.99, "stock": 42}]

async def get_sales_data(start_date: str = None, end_date: str = None, product_id: str = None):
    """Placeholder: Get sales data from database"""
    # This would be implemented to query your actual sales database
    return [{"date": "2023-05-01", "product_id": "123", "quantity": 5, "revenue": 499.95}]

async def get_inventory_metrics(low_stock_threshold: int = 10):
    """Placeholder: Get inventory metrics"""
    # This would query your inventory database
    return {
        "total_products": 150,
        "low_stock_items": 12,
        "out_of_stock_items": 3,
        "total_inventory_value": 45000
    }

async def get_business_metrics(period: str = "month"):
    """Placeholder: Get business performance metrics"""
    # This would aggregate data from your sales and financial databases
    return {
        "revenue": 25000,
        "profit": 8500,
        "growth_rate": 0.12,
        "average_order_value": 85.50
    }

async def get_marketing_metrics(channel: str = None):
    """Placeholder: Get marketing and advertising metrics"""
    # This would pull data from your marketing platforms
    return {
        "ad_spend": 2000,
        "impressions": 50000,
        "clicks": 2500,
        "conversion_rate": 0.03,
        "cost_per_acquisition": 25.00
    }

# Original Product class from the upselling agent
class Product(BaseModel):
    """
    Use to find a product based on user query
    """
    name: str = Field(description="The name of the product")

    async def execute(self):
        search_terms = await get_products(name=self.name)
        results = search_terms
        return results

# New models for business analytics
class DateRange(BaseModel):
    """Date range for querying business data"""
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    end_date: str = Field(description="End date in YYYY-MM-DD format")

class SalesMetrics(BaseModel):
    """
    Use to retrieve sales metrics for a specific period
    """
    date_range: Optional[DateRange] = Field(None, description="Date range for the sales data")
    product_id: Optional[str] = Field(None, description="Filter by specific product ID")
    
    async def execute(self):
        start_date = None
        end_date = None
        
        if self.date_range:
            start_date = self.date_range.start_date
            end_date = self.date_range.end_date
        
        sales_data = await get_sales_data(
            start_date=start_date,
            end_date=end_date,
            product_id=self.product_id
        )
        
        # Calculate additional metrics
        total_revenue = sum(item["revenue"] for item in sales_data)
        total_units = sum(item["quantity"] for item in sales_data)
        
        return {
            "sales_data": sales_data,
            "summary": {
                "total_revenue": total_revenue,
                "total_units_sold": total_units,
                "average_price": total_revenue / total_units if total_units > 0 else 0
            }
        }

class InventoryStatus(BaseModel):
    """
    Use to check inventory status and identify low stock items
    """
    low_stock_threshold: int = Field(10, description="Threshold to identify low stock items")
    
    async def execute(self):
        inventory_metrics = await get_inventory_metrics(low_stock_threshold=self.low_stock_threshold)
        return inventory_metrics

class BusinessPerformance(BaseModel):
    """
    Use to analyze overall business performance
    """
    period: Literal["day", "week", "month", "quarter", "year"] = Field(
        "month", description="Time period for analysis"
    )
    
    async def execute(self):
        business_metrics = await get_business_metrics(period=self.period)
        return business_metrics

class MarketingAnalytics(BaseModel):
    """
    Use to analyze marketing and advertising performance
    """
    channel: Optional[str] = Field(None, description="Specific marketing channel to analyze")
    
    async def execute(self):
        marketing_metrics = await get_marketing_metrics(channel=self.channel)
        return marketing_metrics

class UpsellRecommendation(BaseModel):
    """
    Use to get upselling recommendations for specific products
    """
    product: str = Field(description="Product to get upselling recommendations for")
    intent: Literal["purchased", "inquired"] = Field(
        "purchased", description="Context of the product interaction"
    )
    
    async def execute(self):
        # This uses the original upselling agent as a tool
        from upselling_agent import run_upselling_agent
        recommendations = await run_upselling_agent(product=self.product, intent=self.intent)
        return {"recommendations": recommendations}


# System prompt for the business analytics agent
BUSINESS_SYSTEM_PROMPT = """
You are a Business Analytics Assistant that helps business owners understand their business performance, 
inventory status, sales metrics, and marketing effectiveness. You can provide insights, generate reports, 
and answer questions about various aspects of the business.

When responding:
1. Be concise and data-driven
2. Highlight key insights and trends
3. Provide actionable recommendations when appropriate
4. Use appropriate business terminology
5. Format numerical data clearly with proper units

You have access to various tools to retrieve business data. Use them appropriately based on the 
business owner's request.
"""

# Define tools for the business analytics agent
BUSINESS_TOOLS = [
    openai.pydantic_function_tool(Product),
    openai.pydantic_function_tool(SalesMetrics),
    openai.pydantic_function_tool(InventoryStatus),
    openai.pydantic_function_tool(BusinessPerformance),
    openai.pydantic_function_tool(MarketingAnalytics),
    openai.pydantic_function_tool(UpsellRecommendation),
]

BUSINESS_TOOLS_MAP = {
    "Product": Product,
    "SalesMetrics": SalesMetrics,
    "InventoryStatus": InventoryStatus,
    "BusinessPerformance": BusinessPerformance,
    "MarketingAnalytics": MarketingAnalytics,
    "UpsellRecommendation": UpsellRecommendation,
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
        output = await BUSINESS_TOOLS_MAP[tool_name](**tool_arguments).execute()
        messages.append(
            {
                "role": "tool",
                "name": tool_name,
                "tool_call_id": tool_call_id,
                "content": json.dumps(output),
            }
        )
    return messages

async def run_business_agent(query: str, chat_history=None, **kwargs):
    """
    Processes business owner queries about business performance, inventory, sales, etc.
    
    Args:
        query (str): The business owner's question or request
        chat_history (list, optional): Previous interactions. Defaults to None.
        **kwargs: Additional parameters.
        
    Returns:
        str: Response with business insights, metrics, or recommendations based on the query
    """
    if chat_history is None:
        chat_history = []
        
    chat_history.append({"role": "user", "content": query})
    
    messages = [{"role": "system", "content": BUSINESS_SYSTEM_PROMPT}]
    messages.extend(chat_history)
    
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0,
            tools=BUSINESS_TOOLS,
        )
        
        if response.choices[0].message.tool_calls:
            chat_history.append(response.choices[0].message)
            messages = await execute_tool(
                response.choices[0].message.tool_calls, messages
            )
        else:
            return response.choices[0].message.content

if __name__ == "__main__":
    import asyncio

    async def main():
        # Example queries to test the business agent
        queries = [
            "How are our sales performing this month?",
            "Do we have any products that are running low on inventory?",
            "What's our marketing ROI for the last quarter?",
            "Which products should we consider for upselling with our leather bags?"
        ]
        
        for query in queries:
            print(f"\nQuery: {query}")
            print("-" * 50)
            response = await run_business_agent(query)
            print(f"Response: {response}")
            print("=" * 80)

    asyncio.run(main())