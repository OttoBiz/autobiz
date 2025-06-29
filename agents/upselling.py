"""Intelligent Upselling Agent using Pydantic-AI with smart context awareness."""

from typing import List, Optional, Union, Literal
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext

from models import Product


# ============================================================================
# Dependencies and Context Models
# ============================================================================

class UpsellingAgentDeps(BaseModel):
    """Dependencies for the Upselling Agent."""
    business_id: int
    max_suggestions: int = 3
    min_price_threshold: float = 10.0


class PurchaseContext(BaseModel):
    """Context for upselling scenarios."""
    purchased_product: Product
    quantity: int
    scenario: Literal["checkout", "post_purchase", "customer_service", "follow_up"] = "post_purchase"


class UnavailableProductContext(BaseModel):
    """Context for suggesting alternatives to unavailable products."""
    searched_product_name: str
    customer_budget: Optional[float] = None


# ============================================================================
# Response Models
# ============================================================================

class ComplementaryUpsell(BaseModel):
    """Response for complementary product suggestions."""
    result_type: Literal["complementary"] = "complementary"
    suggested_products: List[Product]
    reasoning: str
    upsell_message: str


class AlternativeProducts(BaseModel):
    """Response for alternative product suggestions."""
    result_type: Literal["alternatives"] = "alternatives"
    alternative_products: List[Product]
    explanation: str


class NoUpsellRecommended(BaseModel):
    """Response when no upselling is appropriate."""
    result_type: Literal["no_upsell"] = "no_upsell"
    reason: str


# Union type for all possible upselling responses
UpsellingResponse = Union[
    ComplementaryUpsell,
    AlternativeProducts,
    NoUpsellRecommended
]


# ============================================================================
# Upselling Agent Definition
# ============================================================================

upselling_agent = Agent(
    model='openai:gpt-4o-mini',
    deps_type=UpsellingAgentDeps,
)


@upselling_agent.system_prompt
def upselling_system_prompt(ctx: RunContext[UpsellingAgentDeps]) -> str:
    """Universal intelligent system prompt for any product category."""
    return f"""You are an intelligent upselling specialist for business ID {ctx.deps.business_id}.

CORE PRINCIPLE: Customer satisfaction and logical value come first, not aggressive sales.

UNIVERSAL PRODUCT INTELLIGENCE:

You work with ANY type of business - electronics, clothing, food, furniture, books, sports, beauty, etc. 
Your job is to understand product relationships for ANY category and make smart recommendations based on actual inventory.

**UNIVERSAL COMPLEMENTARY EXAMPLES**:

1. **Electronics**: Phone → case, charger, earbuds | Laptop → mouse, bag, stand | TV → cables, mount
2. **Clothing**: Dress → shoes, jewelry, bag | Suit → tie, shoes, belt | Jacket → pants, shirt  
3. **Food & Beverage**: Pizza → drinks, dessert | Coffee → pastries, sugar | Burger → fries, drink
4. **Furniture**: Sofa → cushions, coffee table | Bed → pillows, sheets, mattress | Desk → chair, lamp
5. **Books**: Cookbook → kitchen tools | Fitness book → equipment | Novel → bookmarks, reading light
6. **Sports**: Tennis racket → balls, strings | Running shoes → socks, gear | Gym membership → equipment
7. **Beauty**: Foundation → primer, brushes | Skincare → cleanser, moisturizer | Lipstick → liner, gloss
8. **Home & Garden**: Paint → brushes, primer | Plants → pots, soil | Tools → safety gear
9. **Automotive**: Car parts → installation tools | Oil → filters | Tires → balancing
10. **Baby/Kids**: Diapers → wipes, cream | Toys → batteries, accessories | Clothes → matching items

**SCENARIO-BASED INTELLIGENCE**:
- **"checkout"**: Customer actively buying, open to logical additions
- **"post_purchase"**: Just bought, suggest protection/enhancement items only  
- **"customer_service"**: Be very conservative - only suggest if genuinely helpful to their situation
- **"follow_up"**: Later contact, broader complementary items acceptable

**UNIVERSAL RULES**:

1. **Primary vs Accessory Intelligence**:
   - Primary products (main purchases): Suggest accessories, NOT upgrades
   - Accessories: Usually no further upselling needed
   - Consumables: Suggest related consumables or tools

2. **Natural Relationships** (analyze purchased product to determine):
   - What LOGICALLY goes together for this product category?
   - What ENHANCES the primary purchase experience?
   - What PROTECTS or MAINTAINS the purchase?
   - What COMPLETES the customer's needs?

3. **Smart "No Upsell" Decisions**:
   - Customer just bought the main item they need
   - Product price under ${ctx.deps.min_price_threshold}
   - Customer bought accessories (they likely have what they need)
   - No logical complements exist in current inventory
   - Customer service contexts where sales would feel inappropriate

4. **Inventory-First Analysis**:
   - Only work with products actually available in inventory
   - Only suggest products that are in stock (stock > 0)
   - Only suggest active products (is_active = True)
   - If no good complements exist in inventory → gracefully decline

**YOUR WORKFLOW**:

When asked to analyze upselling opportunities, follow this intelligent workflow:

1. **Primary Upselling Analysis**: 
   - Use `analyze_complementary_upsell` with the purchase context
   - This tool does validation + inventory filtering and returns ALL suitable candidates
   - YOU must intelligently select the BEST complementary products from the filtered pool
   - Respect the max_suggestions limit (typically {ctx.deps.max_suggestions}) in your final recommendations
   - Focus on products that genuinely complement the purchased item

2. **For Alternative Product Scenarios**:
   - Use `suggest_alternatives_for_unavailable` when a customer wants something out of stock
   - Consider budget constraints and product categories

3. **Spot Checks**:
   - Use `check_product_availability` when you need to verify specific products

**CUSTOMER SERVICE INTELLIGENCE**:
For customer service scenarios, be especially thoughtful:
- ✅ Customer asking "what accessories work with this?" → Perfect for helpful suggestions
- ✅ Customer satisfied after resolving an issue → Might be open to enhancements
- ❌ Customer complaining about defective product → Focus on resolution, not sales
- ❌ Customer requesting refund/return → Prioritize their concerns

**YOUR PRODUCT RELATION INTELLIGENCE**: 
Think about product categories and natural relationships. A phone naturally goes with cases and chargers. A dress pairs with shoes and jewelry. Food goes with drinks. When you receive filtered candidates from your tools, analyze them intelligently to select the BEST complements - don't just return everything.

**SELECTION CRITERIA FOR FINAL RECOMMENDATIONS**:
1. **True Complementary Value**: Does this product genuinely enhance the primary purchase?
2. **Natural Usage Together**: Would customers logically use these items together?
3. **Price Appropriateness**: Is the suggested item reasonably priced relative to the main purchase?
4. **Customer Benefit**: Does this add real value to the customer's experience?

**IMPORTANT**: Your tools provide pre-filtered candidates based on business rules. You must apply AI intelligence to select the most appropriate complements from these candidates, respecting the max_suggestions limit."""


# ============================================================================
# Upselling Agent Tools
# ============================================================================

@upselling_agent.tool
def analyze_complementary_upsell(
    ctx: RunContext[UpsellingAgentDeps],
    purchase_context: PurchaseContext
) -> UpsellingResponse:
    """Analyze if complementary upselling is appropriate for a purchased product."""
    
    try:
        purchased_product = purchase_context.purchased_product
        scenario = purchase_context.scenario
        
        # Check if product price is below threshold
        if purchased_product.price < ctx.deps.min_price_threshold:
            return NoUpsellRecommended(
                reason=f"Product price (${purchased_product.price:.2f}) is below minimum threshold for upselling (${ctx.deps.min_price_threshold:.2f})"
            )
        
        # Basic validation passed - proceed with actual inventory analysis
        # Instead of returning confusing "NoUpsellRecommended", do the real analysis
        
        # Get all available products from the business inventory
        from services.db import list_products_by_business
        
        all_products = list_products_by_business(
            business_id=ctx.deps.business_id,
            active_only=True
        )
        
        # Filter out the purchased product and out-of-stock items
        available_products = [
            p for p in all_products 
            if p.id != purchased_product.id and p.stock > 0
        ]
        
        if not available_products:
            return NoUpsellRecommended(
                reason="No other products available in inventory for complementary suggestions."
            )
        
        # Filter by reasonable price range - let AI make final decisions
        reasonable_products = [
            p for p in available_products 
            if p.price <= purchased_product.price * 3
        ]
        
        if not reasonable_products:
            return NoUpsellRecommended(
                reason="No products in reasonable price range for complementary suggestions."
            )
        
        # Apply scenario-based logic - provide full filtered pool to AI for intelligent selection
        if scenario == "customer_service":
            # Very conservative - only suggest if genuinely helpful
            # Limit to protection/enhancement items at lower price points
            candidate_products = [
                p for p in reasonable_products 
                if p.price <= purchased_product.price * 0.8
            ]  # Let AI choose best options from conservative pool
        elif scenario == "post_purchase":
            # Conservative - protection/enhancement focus, but give AI full pool
            candidate_products = reasonable_products
        elif scenario == "checkout":
            # More open - broader range, full pool for AI analysis
            candidate_products = reasonable_products
        else:
            # Default moderate approach - full pool for AI analysis
            candidate_products = reasonable_products
        
        if candidate_products:
            return ComplementaryUpsell(
                suggested_products=candidate_products,
                reasoning=f"Found {len(candidate_products)} complementary products that work well with {purchased_product.name} (scenario: {scenario}).",
                upsell_message=f"Great choice on the {purchased_product.name}! You might also like these items from our inventory:"
            )
        else:
            return NoUpsellRecommended(
                reason=f"No suitable complementary products found for {scenario} scenario."
            )
        
    except Exception:
        return NoUpsellRecommended(
            reason="Unable to analyze upselling opportunities due to technical error."
        )



@upselling_agent.tool
def suggest_alternatives_for_unavailable(
    ctx: RunContext[UpsellingAgentDeps],
    unavailable_context: UnavailableProductContext
) -> UpsellingResponse:
    """Suggest available alternatives when a product is unavailable."""
    from services.db import search_products
    
    try:
        search_query = unavailable_context.searched_product_name
        customer_budget = unavailable_context.customer_budget
        
        # Search for similar products
        similar_products = search_products(
            business_id=ctx.deps.business_id,
            query=search_query,
            active_only=True
        )
        
        # Filter by availability (stock > 0)
        available_alternatives = [p for p in similar_products if p.stock > 0]
        
        # Filter by budget if provided
        if customer_budget:
            available_alternatives = [p for p in available_alternatives if p.price <= customer_budget]
        
        if available_alternatives:
            # Limit to max suggestions
            suggested_alternatives = available_alternatives[:ctx.deps.max_suggestions]
            
            budget_msg = f" within your budget of ${customer_budget:.2f}" if customer_budget else ""
            
            return AlternativeProducts(
                alternative_products=suggested_alternatives,
                explanation=f"I found these available alternatives to '{search_query}'{budget_msg}. All are currently in stock."
            )
        else:
            budget_msg = " within your specified budget" if customer_budget else ""
            return NoUpsellRecommended(
                reason=f"No suitable alternatives found for '{search_query}'{budget_msg} that are currently in stock."
            )
            
    except Exception:
        return NoUpsellRecommended(
            reason="Unable to find alternatives due to technical error."
        )


@upselling_agent.tool
def check_product_availability(
    ctx: RunContext[UpsellingAgentDeps],
    product_id: int
) -> bool:
    """Check if a specific product is available for upselling."""
    from services.db import get_product_by_id
    
    try:
        product = get_product_by_id(product_id)
        if product and product.is_active and product.stock > 0:
            return True
        return False
    except Exception:
        return False


# ============================================================================
# Helper Functions
# ============================================================================

def create_purchase_context(
    purchased_product: Product,
    quantity: int = 1,
    scenario: Literal["checkout", "post_purchase", "customer_service", "follow_up"] = "post_purchase"
) -> PurchaseContext:
    """Create a PurchaseContext for upselling analysis."""
    return PurchaseContext(
        purchased_product=purchased_product,
        quantity=quantity,
        scenario=scenario
    )


def create_unavailable_context(
    searched_product_name: str,
    customer_budget: Optional[float] = None
) -> UnavailableProductContext:
    """Create an UnavailableProductContext for alternative suggestions."""
    return UnavailableProductContext(
        searched_product_name=searched_product_name,
        customer_budget=customer_budget
    )


def analyze_upsell_opportunity(
    purchased_product: Product,
    business_id: int,
    quantity: int = 1,
    scenario: Literal["checkout", "post_purchase", "customer_service", "follow_up"] = "post_purchase",
    max_suggestions: int = 3
):
    """Convenience function to analyze upselling opportunities after a purchase."""
    deps = UpsellingAgentDeps(
        business_id=business_id,
        max_suggestions=max_suggestions
    )
    
    # Include quantity and scenario information in the message for AI context
    quantity_msg = f" (quantity: {quantity})" if quantity != 1 else ""
    return upselling_agent.run_sync(
        f"Analyze complementary upselling opportunities for {purchased_product.name}{quantity_msg} (scenario: {scenario})",
        deps=deps,
        message_history=[]
    )


def find_alternatives(
    unavailable_product_name: str,
    business_id: int,
    customer_budget: Optional[float] = None,
    max_suggestions: int = 3
):
    """Convenience function to find alternatives for unavailable products."""
    deps = UpsellingAgentDeps(
        business_id=business_id,
        max_suggestions=max_suggestions
    )
    
    # Note: context creation is handled internally by the agent
    budget_msg = f" (budget: ${customer_budget})" if customer_budget else ""
    return upselling_agent.run_sync(
        f"Suggest alternatives for unavailable product '{unavailable_product_name}'{budget_msg}",
        deps=deps,
        message_history=[]
    )
