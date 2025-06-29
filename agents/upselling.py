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
    """Intelligent system prompt for context-aware upselling."""
    return f"""You are an intelligent upselling specialist for business ID {ctx.deps.business_id}.

CORE PRINCIPLE: Customer satisfaction and logical value come first, not aggressive sales.

SMART UPSELLING RULES:

1. **For Primary Products** (phones, laptops, TVs, gaming consoles, cameras):
   - NEVER suggest upgrades or similar primary products
   - ONLY suggest complementary accessories/protection
   - Examples:
     * Phone → Case, screen protector, wireless charger, earbuds (NOT better phone)
     * Laptop → Mouse, laptop bag, external monitor, keyboard (NOT laptop upgrade)
     * TV → HDMI cables, wall mount, streaming device (NOT bigger TV)
     * Gaming console → Games, controllers, headset (NOT console upgrade)

2. **Scenario-Based Upselling**:
   - **"checkout"**: Customer actively buying, open to additions (full range of complements)
   - **"post_purchase"**: Just completed purchase, suggest protection/essential accessories only
   - **"customer_service"**: Customer had issues, be very conservative (often no upsell)
   - **"follow_up"**: Later contact, more open to broader complementary items

3. **For Accessories/Complementary Items** (cases, cables, stands, bags):
   - Usually NO upselling needed - customer already bought what they need
   - Only suggest if there's clear additional value
   - Example: Bought phone case → Maybe screen protector, but probably nothing

4. **For Unavailable Products**:
   - Suggest similar available alternatives in same category
   - Match or similar price range if budget provided
   - ALWAYS confirm availability before suggesting

5. **Availability Confirmation MANDATORY**:
   - NEVER suggest out-of-stock products (stock = 0)
   - NEVER suggest inactive products (is_active = False)
   - Check stock levels before any recommendation

6. **When to Say NO to Upselling**:
   - Customer just purchased primary product → No upgrades/alternatives
   - Very cheap items (under ${ctx.deps.min_price_threshold}) → Not worth upselling effort
   - Customer bought accessories → They likely have what they need
   - No logical complements exist for the product category
   - All potential complements are unavailable
   - Customer service scenarios → Be very conservative

7. **Product Category Intelligence**:
   - Understand product relationships from names and descriptions
   - Recognize primary vs accessory products
   - Know what naturally goes together
   - Respect purchase timing and customer intent

Your tools return different response types based on the scenario. Always choose the most appropriate response type and provide clear reasoning for your decisions.

Focus on being genuinely helpful rather than pushy. A satisfied customer is more valuable than an oversold customer."""


# ============================================================================
# Upselling Agent Tools
# ============================================================================

@upselling_agent.tool
def analyze_complementary_upsell(
    ctx: RunContext[UpsellingAgentDeps],
    purchase_context: PurchaseContext
) -> UpsellingResponse:
    """Analyze if complementary upselling is appropriate for a purchased product."""
    from services.db import search_products
    
    try:
        purchased_product = purchase_context.purchased_product
        product_name = purchased_product.name.lower()
        scenario = purchase_context.scenario
        
        # Check if product price is below threshold
        if purchased_product.price < ctx.deps.min_price_threshold:
            return NoUpsellRecommended(
                reason=f"Product price (${purchased_product.price:.2f}) is below minimum threshold for upselling (${ctx.deps.min_price_threshold:.2f})"
            )
        
        # Customer service scenario - be very conservative
        if scenario == "customer_service":
            return NoUpsellRecommended(
                reason="Prioritizing customer satisfaction over additional sales due to service context."
            )
        
        # Detect primary products that shouldn't get upgrade suggestions
        primary_indicators = ["phone", "laptop", "macbook", "iphone", "samsung", "tv", "television", 
                            "console", "playstation", "xbox", "camera", "ipad", "tablet", "monitor"]
        
        is_primary_product = any(indicator in product_name for indicator in primary_indicators)
        
        if is_primary_product:
            # Look for complementary accessories based on scenario
            complementary_terms = []
            
            # Define base complementary terms for each product type
            if any(term in product_name for term in ["phone", "iphone", "samsung"]):
                base_terms = ["case", "charger", "cable", "screen protector", "earbuds", "headphones"]
            elif any(term in product_name for term in ["laptop", "macbook"]):
                base_terms = ["mouse", "bag", "sleeve", "stand", "keyboard", "monitor", "hub"]
            elif any(term in product_name for term in ["tv", "television"]):
                base_terms = ["cable", "mount", "remote", "streaming", "soundbar"]
            elif any(term in product_name for term in ["console", "playstation", "xbox"]):
                base_terms = ["controller", "headset", "game", "cable", "stand"]
            elif any(term in product_name for term in ["camera"]):
                base_terms = ["lens", "tripod", "memory", "bag", "battery", "charger"]
            else:
                base_terms = []
            
            # Adjust suggestions based on scenario
            if scenario == "checkout":
                # Customer is actively buying, more open to additions
                complementary_terms = base_terms  # Full range
            elif scenario == "post_purchase":
                # Just bought, suggest protection/essential accessories only
                protection_terms = ["case", "protector", "bag", "sleeve", "mount", "stand"]
                complementary_terms = [term for term in base_terms if any(prot in term for prot in protection_terms)]
                if not complementary_terms:  # If no protection items, use first 2-3 base terms
                    complementary_terms = base_terms[:3]
            elif scenario == "follow_up":
                # Later contact, could suggest broader complementary items
                complementary_terms = base_terms + ["upgrade", "premium"]  # Slightly more expansive
            else:
                complementary_terms = base_terms
            
            if complementary_terms:
                # Search for complementary products
                potential_complements = []
                for term in complementary_terms:
                    found_products = search_products(
                        business_id=ctx.deps.business_id,
                        query=term,
                        active_only=True
                    )
                    # Only include products that are in stock
                    available_products = [p for p in found_products if p.stock > 0]
                    potential_complements.extend(available_products)
                
                # Remove duplicates and limit results
                seen_ids = set()
                unique_complements = []
                for product in potential_complements:
                    if product.id not in seen_ids and product.id != purchased_product.id:
                        unique_complements.append(product)
                        seen_ids.add(product.id)
                
                if unique_complements:
                    # Limit to max suggestions
                    suggested_products = unique_complements[:ctx.deps.max_suggestions]
                    
                    return ComplementaryUpsell(
                        suggested_products=suggested_products,
                        reasoning=f"Customer purchased {purchased_product.name}. Suggesting complementary accessories that enhance the experience.",
                        upsell_message=f"Great choice on the {purchased_product.name}! Here are some accessories that work perfectly with it:"
                    )
        
        # For accessory products, usually no upselling needed
        accessory_indicators = ["case", "cable", "charger", "bag", "stand", "mount", "adapter"]
        is_accessory = any(indicator in product_name for indicator in accessory_indicators)
        
        if is_accessory:
            return NoUpsellRecommended(
                reason="Customer purchased an accessory product. They likely have what they need for their setup."
            )
        
        # If we reach here, no clear upselling opportunity
        return NoUpsellRecommended(
            reason="No suitable complementary products identified for this purchase."
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
    scenario: str = "post_purchase",
    max_suggestions: int = 3
):
    """Convenience function to analyze upselling opportunities after a purchase."""
    deps = UpsellingAgentDeps(
        business_id=business_id,
        max_suggestions=max_suggestions
    )
    
    context = create_purchase_context(purchased_product, quantity, scenario)
    return upselling_agent.run_sync(
        "Analyze complementary upselling opportunities for this purchase",
        deps=deps
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
    
    context = create_unavailable_context(unavailable_product_name, customer_budget)
    return upselling_agent.run_sync(
        "Suggest alternatives for unavailable product",
        deps=deps
    )


# ============================================================================
# Usage Examples (for documentation)
# ============================================================================

if __name__ == "__main__":
    # Example usage patterns:
    
    print("Intelligent Upselling Agent Examples:")
    print("\n1. Scenario-Based Upselling:")
    print("   - Checkout: Phone + case, charger, earbuds (customer still buying)")
    print("   - Post-purchase: Phone → case, screen protector (protection focus)")
    print("   - Customer service: Often no upsell (satisfaction priority)")
    print("   - Follow-up: Phone → AirPods, wireless charger (broader options)")
    
    print("\n2. Primary Product Intelligence:")
    print("   - Laptop purchase → mouse, bag, monitor (NOT laptop upgrade)")
    print("   - TV purchase → HDMI cables, mount (NOT bigger TV)")
    print("   - Console purchase → games, controllers (NOT console upgrade)")
    
    print("\n3. Unavailable Product Scenarios:")
    print("   - 'iPhone 15 Pro Max' unavailable → Suggests iPhone 15 Pro, Samsung alternatives")
    print("   - 'Gaming laptop $800' unavailable → Suggests similar laptops under $800")
    
    print("\n4. Smart 'No Upsell' Decisions:")
    print("   - Customer service context → Be very conservative")
    print("   - Bought accessory → Customer likely has what they need") 
    print("   - Very cheap purchase → Not worth upselling effort")
    print("   - No good complements exist → Graceful decline")