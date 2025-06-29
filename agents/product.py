"""Product Agent using Pydantic-AI for flexible product database queries."""

from typing import List, Optional, Union, Literal
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from models import Product


# ============================================================================
# Dependencies and Response Models
# ============================================================================

class ProductAgentDeps(BaseModel):
    """Dependencies for the Product Agent."""
    business_id: int
    max_results: int = 50


class ProductSearchResult(BaseModel):
    """Response for product search queries."""
    result_type: Literal["search"] = "search"
    products: List[Product]
    total_found: int
    search_query: str


class ProductAvailabilityResult(BaseModel):
    """Response for product availability checks."""
    result_type: Literal["availability"] = "availability"
    product: Optional[Product]
    available: bool
    stock_level: int
    product_name: str


class ProductListResult(BaseModel):
    """Response for product catalog listing."""
    result_type: Literal["list"] = "list"
    products: List[Product]
    total_count: int


# Union type for all possible agent responses
ProductAgentResponse = Union[
    ProductSearchResult,
    ProductAvailabilityResult,
    ProductListResult
]


# ============================================================================
# Product Agent Definition
# ============================================================================

product_agent = Agent(
    model='openai:gpt-4o-mini',
    deps_type=ProductAgentDeps,
)


@product_agent.system_prompt
def product_system_prompt(ctx: RunContext[ProductAgentDeps]) -> str:
    """System prompt for the product agent."""
    return f"""You are a product search specialist for business ID {ctx.deps.business_id}.

Your role is to help customers find products using flexible search capabilities. You have access to three tools that return different response types:

1. **search_products_by_query** → ProductSearchResult
   - Use for: "Find X", "Search for X", "Show me X products"
   - Handles general product searches with text matching

2. **check_product_availability** → ProductAvailabilityResult  
   - Use for: "Is X available?", "X in stock?", "Do you have X?"
   - Checks specific product availability and stock levels

3. **list_all_products** → ProductListResult
   - Use for: "Show all products", "What do you have?", "Product catalog"
   - Lists all available products in the catalog

Choose the most appropriate tool based on the customer's query intent. Always provide helpful, accurate information about products including names, prices, descriptions, and stock availability.

Focus on being helpful and informative while staying within your role as a product search specialist."""


# ============================================================================
# Product Agent Tools
# ============================================================================

@product_agent.tool
def search_products_by_query(
    ctx: RunContext[ProductAgentDeps], 
    search_query: str
) -> ProductSearchResult:
    """Search for products using flexible text matching on names and descriptions."""
    from services.db import search_products
    
    try:
        products = search_products(
            business_id=ctx.deps.business_id,
            query=search_query,
            active_only=True
        )
        
        # Limit results based on max_results setting
        limited_products = products[:ctx.deps.max_results]
        
        return ProductSearchResult(
            products=limited_products,
            total_found=len(products),
            search_query=search_query
        )
    
    except Exception:
        # Return empty result on error
        return ProductSearchResult(
            products=[],
            total_found=0,
            search_query=search_query
        )


@product_agent.tool
def check_product_availability(
    ctx: RunContext[ProductAgentDeps],
    product_name: str
) -> ProductAvailabilityResult:
    """Check if a specific product is available and get stock information."""
    from services.db import search_products
    
    try:
        # Search for products matching the name
        products = search_products(
            business_id=ctx.deps.business_id,
            query=product_name,
            active_only=True
        )
        
        if products:
            # Use the first (best) match
            product = products[0]
            available = product.stock > 0
            
            return ProductAvailabilityResult(
                product=product,
                available=available,
                stock_level=product.stock,
                product_name=product_name
            )
        else:
            # No product found
            return ProductAvailabilityResult(
                product=None,
                available=False,
                stock_level=0,
                product_name=product_name
            )
    
    except Exception:
        # Return unavailable on error
        return ProductAvailabilityResult(
            product=None,
            available=False,
            stock_level=0,
            product_name=product_name
        )


@product_agent.tool
def list_all_products(
    ctx: RunContext[ProductAgentDeps]
) -> ProductListResult:
    """List all available products in the catalog."""
    from services.db import list_products_by_business
    
    try:
        products = list_products_by_business(
            business_id=ctx.deps.business_id,
            active_only=True
        )
        
        # Limit results based on max_results setting
        limited_products = products[:ctx.deps.max_results]
        
        return ProductListResult(
            products=limited_products,
            total_count=len(products)
        )
    
    except Exception:
        # Return empty list on error
        return ProductListResult(
            products=[],
            total_count=0
        )


# ============================================================================
# Helper Functions
# ============================================================================

def create_product_agent_deps(business_id: int, max_results: int = 50) -> ProductAgentDeps:
    """Create ProductAgentDeps with validation."""
    return ProductAgentDeps(
        business_id=business_id,
        max_results=max_results
    )


def run_product_query(query: str, business_id: int, max_results: int = 50):
    """Convenience function to run a product query."""
    deps = create_product_agent_deps(business_id, max_results)
    return product_agent.run_sync(query, deps=deps)
