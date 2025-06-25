"""Finite State Machine for WhatsApp AI Assistant order management."""

from enum import Enum
from typing import List, Dict, Optional, Set
from dataclasses import dataclass


class OrderState(str, Enum):
    """Order states in the customer journey."""

    # Initial states
    GREETING = "greeting"
    BROWSING = "browsing"

    # Shopping states
    VIEWING_PRODUCT = "viewing_product"
    ADDING_TO_CART = "adding_to_cart"
    CART_REVIEW = "cart_review"

    # Checkout states
    CHECKOUT = "checkout"
    COLLECTING_ADDRESS = "collecting_address"
    CONFIRMING_ORDER = "confirming_order"

    # Payment states
    PAYMENT_PENDING = "payment_pending"
    PAYMENT_PROCESSING = "payment_processing"
    PAYMENT_VERIFIED = "payment_verified"
    PAYMENT_FAILED = "payment_failed"

    # Delivery states
    DELIVERY_SCHEDULED = "delivery_scheduled"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"

    # Completion states
    ORDER_COMPLETED = "order_completed"

    # Support states
    ESCALATED_TO_HUMAN = "escalated_to_human"
    CUSTOMER_SUPPORT = "customer_support"

    # Error states
    ERROR = "error"
    TIMEOUT = "timeout"


class ConversationState(str, Enum):
    """High-level conversation states."""

    ACTIVE = "active"
    PAUSED = "paused"
    WAITING_FOR_INPUT = "waiting_for_input"
    WAITING_FOR_PAYMENT = "waiting_for_payment"
    WAITING_FOR_DELIVERY = "waiting_for_delivery"
    COMPLETED = "completed"
    ESCALATED = "escalated"


@dataclass
class StateTransition:
    """Represents a valid state transition."""

    from_state: OrderState
    to_state: OrderState
    trigger: str
    condition: Optional[str] = None
    action: Optional[str] = None


class OrderStateMachine:
    """Finite State Machine for order management."""

    # Define valid state transitions
    TRANSITIONS: List[StateTransition] = [
        # Initial flow
        StateTransition(OrderState.GREETING, OrderState.BROWSING, "start_browsing"),
        StateTransition(OrderState.BROWSING, OrderState.VIEWING_PRODUCT, "view_product"),

        # Shopping flow
        StateTransition(OrderState.VIEWING_PRODUCT, OrderState.ADDING_TO_CART, "add_to_cart"),
        StateTransition(OrderState.VIEWING_PRODUCT, OrderState.BROWSING, "continue_browsing"),
        StateTransition(OrderState.ADDING_TO_CART, OrderState.CART_REVIEW, "review_cart"),
        StateTransition(OrderState.ADDING_TO_CART, OrderState.BROWSING, "continue_shopping"),

        # Cart management
        StateTransition(OrderState.CART_REVIEW, OrderState.BROWSING, "continue_shopping"),
        StateTransition(OrderState.CART_REVIEW, OrderState.CHECKOUT, "proceed_to_checkout"),
        StateTransition(OrderState.CART_REVIEW, OrderState.VIEWING_PRODUCT, "view_product"),

        # Checkout flow
        StateTransition(OrderState.CHECKOUT, OrderState.COLLECTING_ADDRESS, "collect_address"),
        StateTransition(OrderState.COLLECTING_ADDRESS, OrderState.CONFIRMING_ORDER, "confirm_order"),
        StateTransition(OrderState.CONFIRMING_ORDER, OrderState.PAYMENT_PENDING, "initiate_payment"),

        # Payment flow
        StateTransition(OrderState.PAYMENT_PENDING, OrderState.PAYMENT_PROCESSING, "payment_started"),
        StateTransition(OrderState.PAYMENT_PROCESSING, OrderState.PAYMENT_VERIFIED, "payment_success"),
        StateTransition(OrderState.PAYMENT_PROCESSING, OrderState.PAYMENT_FAILED, "payment_failed"),
        StateTransition(OrderState.PAYMENT_FAILED, OrderState.PAYMENT_PENDING, "retry_payment"),
        StateTransition(OrderState.PAYMENT_VERIFIED, OrderState.DELIVERY_SCHEDULED, "schedule_delivery"),

        # Delivery flow
        StateTransition(OrderState.DELIVERY_SCHEDULED, OrderState.OUT_FOR_DELIVERY, "start_delivery"),
        StateTransition(OrderState.OUT_FOR_DELIVERY, OrderState.DELIVERED, "delivery_complete"),
        StateTransition(OrderState.DELIVERED, OrderState.ORDER_COMPLETED, "confirm_completion"),

        # Support and error flows
        StateTransition(OrderState.BROWSING, OrderState.ESCALATED_TO_HUMAN, "escalate"),
        StateTransition(OrderState.CART_REVIEW, OrderState.ESCALATED_TO_HUMAN, "escalate"),
        StateTransition(OrderState.CHECKOUT, OrderState.ESCALATED_TO_HUMAN, "escalate"),
        StateTransition(OrderState.PAYMENT_FAILED, OrderState.ESCALATED_TO_HUMAN, "escalate"),
        StateTransition(OrderState.ESCALATED_TO_HUMAN, OrderState.CUSTOMER_SUPPORT, "human_takeover"),

        # Back navigation
        StateTransition(OrderState.CHECKOUT, OrderState.CART_REVIEW, "back_to_cart"),
        StateTransition(OrderState.COLLECTING_ADDRESS, OrderState.CHECKOUT, "back_to_checkout"),
        StateTransition(OrderState.CONFIRMING_ORDER, OrderState.COLLECTING_ADDRESS, "back_to_address"),

        # Timeout and error handling
        StateTransition(OrderState.PAYMENT_PENDING, OrderState.TIMEOUT, "payment_timeout"),
        StateTransition(OrderState.TIMEOUT, OrderState.PAYMENT_PENDING, "resume_payment"),

        # Flexible customer flow - allow going back to shopping/cart from payment states
        StateTransition(OrderState.PAYMENT_PENDING, OrderState.CART_REVIEW, "modify_order"),
        StateTransition(OrderState.PAYMENT_PENDING, OrderState.BROWSING, "continue_shopping"),
        StateTransition(OrderState.PAYMENT_FAILED, OrderState.CART_REVIEW, "modify_order"),
        StateTransition(OrderState.PAYMENT_FAILED, OrderState.BROWSING, "continue_shopping"),

        # Allow continuing shopping from checkout states
        StateTransition(OrderState.CHECKOUT, OrderState.BROWSING, "continue_shopping"),
        StateTransition(OrderState.COLLECTING_ADDRESS, OrderState.CART_REVIEW, "modify_order"),
        StateTransition(OrderState.COLLECTING_ADDRESS, OrderState.BROWSING, "continue_shopping"),
        StateTransition(OrderState.CONFIRMING_ORDER, OrderState.CART_REVIEW, "modify_order"),
        StateTransition(OrderState.CONFIRMING_ORDER, OrderState.BROWSING, "continue_shopping"),

        # Cancel order - restart from various states
        StateTransition(OrderState.CHECKOUT, OrderState.GREETING, "cancel_order"),
        StateTransition(OrderState.COLLECTING_ADDRESS, OrderState.GREETING, "cancel_order"),
        StateTransition(OrderState.CONFIRMING_ORDER, OrderState.GREETING, "cancel_order"),
        StateTransition(OrderState.PAYMENT_PENDING, OrderState.GREETING, "cancel_order"),
        StateTransition(OrderState.PAYMENT_FAILED, OrderState.GREETING, "cancel_order"),

        # Allow adding products from checkout states (common customer behavior)
        StateTransition(OrderState.CHECKOUT, OrderState.VIEWING_PRODUCT, "view_product"),
        StateTransition(OrderState.COLLECTING_ADDRESS, OrderState.VIEWING_PRODUCT, "view_product"),

        # Direct navigation improvements
        StateTransition(OrderState.BROWSING, OrderState.CART_REVIEW, "view_cart"),
        StateTransition(OrderState.VIEWING_PRODUCT, OrderState.CART_REVIEW, "view_cart"),
        StateTransition(OrderState.ADDING_TO_CART, OrderState.VIEWING_PRODUCT, "view_product"),
    ]

    def __init__(self):
        """Initialize the state machine."""
        self._build_transition_map()

    def _build_transition_map(self) -> None:
        """Build a map of valid transitions for quick lookup."""
        self.transition_map: Dict[OrderState, Dict[str, OrderState]] = {}

        for transition in self.TRANSITIONS:
            if transition.from_state not in self.transition_map:
                self.transition_map[transition.from_state] = {}

            self.transition_map[transition.from_state][transition.trigger] = transition.to_state

    def is_valid_transition(self, from_state: OrderState, trigger: str) -> bool:
        """Check if a state transition is valid."""
        return (from_state in self.transition_map and
                trigger in self.transition_map[from_state])

    def get_next_state(self, current_state: OrderState, trigger: str) -> Optional[OrderState]:
        """Get the next state for a given trigger."""
        if self.is_valid_transition(current_state, trigger):
            return self.transition_map[current_state][trigger]
        return None

    def get_valid_triggers(self, current_state: OrderState) -> List[str]:
        """Get all valid triggers for the current state."""
        if current_state in self.transition_map:
            return list(self.transition_map[current_state].keys())
        return []

    def get_reachable_states(self, current_state: OrderState) -> Set[OrderState]:
        """Get all states reachable from the current state."""
        if current_state in self.transition_map:
            return set(self.transition_map[current_state].values())
        return set()


class FSMHelper:
    """Helper functions for FSM operations."""

    @staticmethod
    def is_terminal_state(state: OrderState) -> bool:
        """Check if a state is terminal (no further transitions)."""
        terminal_states = {
            OrderState.ORDER_COMPLETED,
            OrderState.CUSTOMER_SUPPORT,
            OrderState.ERROR
        }
        return state in terminal_states

    @staticmethod
    def is_payment_state(state: OrderState) -> bool:
        """Check if a state is payment-related."""
        payment_states = {
            OrderState.PAYMENT_PENDING,
            OrderState.PAYMENT_PROCESSING,
            OrderState.PAYMENT_VERIFIED,
            OrderState.PAYMENT_FAILED
        }
        return state in payment_states

    @staticmethod
    def is_shopping_state(state: OrderState) -> bool:
        """Check if a state is shopping-related."""
        shopping_states = {
            OrderState.BROWSING,
            OrderState.VIEWING_PRODUCT,
            OrderState.ADDING_TO_CART,
            OrderState.CART_REVIEW
        }
        return state in shopping_states

    @staticmethod
    def is_checkout_state(state: OrderState) -> bool:
        """Check if a state is checkout-related."""
        checkout_states = {
            OrderState.CHECKOUT,
            OrderState.COLLECTING_ADDRESS,
            OrderState.CONFIRMING_ORDER
        }
        return state in checkout_states

    @staticmethod
    def is_delivery_state(state: OrderState) -> bool:
        """Check if a state is delivery-related."""
        delivery_states = {
            OrderState.DELIVERY_SCHEDULED,
            OrderState.OUT_FOR_DELIVERY,
            OrderState.DELIVERED
        }
        return state in delivery_states

    @staticmethod
    def requires_user_input(state: OrderState) -> bool:
        """Check if a state requires user input."""
        input_states = {
            OrderState.BROWSING,
            OrderState.VIEWING_PRODUCT,
            OrderState.CART_REVIEW,
            OrderState.CHECKOUT,
            OrderState.COLLECTING_ADDRESS,
            OrderState.CONFIRMING_ORDER,
            OrderState.PAYMENT_FAILED
        }
        return state in input_states

    @staticmethod
    def can_add_products(state: OrderState) -> bool:
        """Check if products can be added in the current state."""
        addable_states = {
            OrderState.BROWSING,
            OrderState.VIEWING_PRODUCT,
            OrderState.ADDING_TO_CART,
            OrderState.CART_REVIEW
        }
        return state in addable_states

    @staticmethod
    def can_modify_cart(state: OrderState) -> bool:
        """Check if the cart can be modified in the current state."""
        modifiable_states = {
            OrderState.BROWSING,
            OrderState.VIEWING_PRODUCT,
            OrderState.ADDING_TO_CART,
            OrderState.CART_REVIEW,
            OrderState.CHECKOUT
        }
        return state in modifiable_states

    @staticmethod
    def get_state_description(state: OrderState) -> str:
        """Get a human-readable description of the state."""
        descriptions = {
            OrderState.GREETING: "Welcoming the customer",
            OrderState.BROWSING: "Customer is browsing products",
            OrderState.VIEWING_PRODUCT: "Customer is viewing a specific product",
            OrderState.ADDING_TO_CART: "Adding product to cart",
            OrderState.CART_REVIEW: "Customer is reviewing their cart",
            OrderState.CHECKOUT: "Customer is in checkout process",
            OrderState.COLLECTING_ADDRESS: "Collecting delivery address",
            OrderState.CONFIRMING_ORDER: "Customer is confirming their order",
            OrderState.PAYMENT_PENDING: "Waiting for payment initiation",
            OrderState.PAYMENT_PROCESSING: "Payment is being processed",
            OrderState.PAYMENT_VERIFIED: "Payment has been verified",
            OrderState.PAYMENT_FAILED: "Payment has failed",
            OrderState.DELIVERY_SCHEDULED: "Delivery has been scheduled",
            OrderState.OUT_FOR_DELIVERY: "Order is out for delivery",
            OrderState.DELIVERED: "Order has been delivered",
            OrderState.ORDER_COMPLETED: "Order process is complete",
            OrderState.ESCALATED_TO_HUMAN: "Issue escalated to human support",
            OrderState.CUSTOMER_SUPPORT: "Human support is handling the case",
            OrderState.ERROR: "An error has occurred",
            OrderState.TIMEOUT: "Session has timed out"
        }
        return descriptions.get(state, f"State: {state}")

    @staticmethod
    def get_conversation_state_from_order_state(order_state: OrderState) -> ConversationState:
        """Map order state to conversation state."""
        mapping = {
            OrderState.GREETING: ConversationState.ACTIVE,
            OrderState.BROWSING: ConversationState.ACTIVE,
            OrderState.VIEWING_PRODUCT: ConversationState.ACTIVE,
            OrderState.ADDING_TO_CART: ConversationState.ACTIVE,
            OrderState.CART_REVIEW: ConversationState.ACTIVE,
            OrderState.CHECKOUT: ConversationState.ACTIVE,
            OrderState.COLLECTING_ADDRESS: ConversationState.WAITING_FOR_INPUT,
            OrderState.CONFIRMING_ORDER: ConversationState.WAITING_FOR_INPUT,
            OrderState.PAYMENT_PENDING: ConversationState.WAITING_FOR_PAYMENT,
            OrderState.PAYMENT_PROCESSING: ConversationState.WAITING_FOR_PAYMENT,
            OrderState.PAYMENT_VERIFIED: ConversationState.ACTIVE,
            OrderState.PAYMENT_FAILED: ConversationState.ACTIVE,
            OrderState.DELIVERY_SCHEDULED: ConversationState.WAITING_FOR_DELIVERY,
            OrderState.OUT_FOR_DELIVERY: ConversationState.WAITING_FOR_DELIVERY,
            OrderState.DELIVERED: ConversationState.ACTIVE,
            OrderState.ORDER_COMPLETED: ConversationState.COMPLETED,
            OrderState.ESCALATED_TO_HUMAN: ConversationState.ESCALATED,
            OrderState.CUSTOMER_SUPPORT: ConversationState.ESCALATED,
            OrderState.ERROR: ConversationState.PAUSED,
            OrderState.TIMEOUT: ConversationState.PAUSED
        }
        return mapping.get(order_state, ConversationState.ACTIVE)

    @staticmethod
    def can_return_to_shopping(state: OrderState) -> bool:
        """Check if customer can return to shopping/browsing from current state."""
        returnable_states = {
            OrderState.PAYMENT_PENDING,
            OrderState.PAYMENT_FAILED,
            OrderState.CHECKOUT,
            OrderState.COLLECTING_ADDRESS,
            OrderState.CONFIRMING_ORDER,
            OrderState.CART_REVIEW,
            OrderState.VIEWING_PRODUCT,
            OrderState.ADDING_TO_CART
        }
        return state in returnable_states

    @staticmethod
    def can_cancel_order(state: OrderState) -> bool:
        """Check if customer can cancel order and restart from current state."""
        cancellable_states = {
            OrderState.CHECKOUT,
            OrderState.COLLECTING_ADDRESS,
            OrderState.CONFIRMING_ORDER,
            OrderState.PAYMENT_PENDING,
            OrderState.PAYMENT_FAILED
        }
        return state in cancellable_states


# Global instances for easy access
fsm = OrderStateMachine()
fsm_helper = FSMHelper()


def transition_to(current_state: OrderState, trigger: str) -> Optional[OrderState]:
    """Convenience function to transition states."""
    return fsm.get_next_state(current_state, trigger)


def validate_transition(current_state: OrderState, trigger: str) -> bool:
    """Convenience function to validate transitions."""
    return fsm.is_valid_transition(current_state, trigger)


def get_available_actions(current_state: OrderState) -> List[str]:
    """Get available actions for the current state."""
    return fsm.get_valid_triggers(current_state)
