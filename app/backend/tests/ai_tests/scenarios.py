"""Scenario definitions: goals and judge rubrics for AI E2E tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

PdfMode = Literal["none", "valid", "inappropriate", "invalid"]
# Receipt upload encoding: formal PDF vs plain prose in PDF vs corrupt bytes (.pdf name).
ReceiptPdfKind = Literal["structured", "plaintext", "corrupt_bytes"]


@dataclass(frozen=True)
class AIScenario:
    id: str
    title: str
    vendor_key: str
    user_key: str
    logistic_key: Optional[str]
    customer_goal: str
    judge_rubric: str
    ground_truth: str = ""
    max_customer_turns: int = 16
    pdf_mode: PdfMode = "none"
    pdf_product: str = ""
    pdf_amount: float = 0.0
    pdf_wrong_product: str = ""
    pdf_wrong_amount: float = 0.0
    pdf_merchant_label: str = "Test Merchant"
    pdf_turn_threshold: int = 999
    receipt_pdf_kind: ReceiptPdfKind = "structured"
    vendor_followup: bool = False
    vendor_instruction: str = ""
    logistics_followup: bool = False
    logistics_instruction: str = ""
    snapshot_vendor_inbox: bool = False


# Bank label from dummy data style (Manny Gadgets); judge uses rubric loosely.
MANNY_BANK_HINT = "GTBank / gtbank style account for Manny Gadgets"


SCENARIOS: list[AIScenario] = [
    AIScenario(
        id="product_available",
        title="Product available — capture name, price, attributes, quantity",
        vendor_key="manny",
        user_key="john",
        logistic_key=None,
        customer_goal=(
            "You want to buy an iPhone 12. Ask if it is in stock, the price, and key details. "
            "Then say you want quantity 2. Keep messages short."
        ),
        ground_truth="Catalog seeds 'iPhone 12' at a deterministic ₦386 NGN (populate.py stable hash for Manny Gadgets UUID + product name).",
        judge_rubric=(
            "Assistant should confirm availability (or fetch via tools) and state price. "
            "Should capture or acknowledge quantity (2). "
            "Must not invent a wildly wrong price for iPhone 12 vs catalog (expect low hundreds NGN in seeded DB). "
            "Factual product attributes may be brief if CSV has limited fields."
        ),
    ),
    AIScenario(
        id="product_variant_similar",
        title="Preferred attribute unavailable — similar product offered",
        vendor_key="tesla",
        user_key="emily",
        logistic_key=None,
        customer_goal=(
            "You want a Brand New BLACK Laptop (Windows). Tesla Tech CSV has laptops with colors — "
            "insist on black first; if only other colors exist, accept a similar in-stock laptop or ask for alternatives. "
            "Do not mention tests."
        ),
        ground_truth="Tesla CSV includes Laptop rows with color Black, Silver, etc.; multiple SKUs.",
        judge_rubric=(
            "Assistant should use product tools. If exact black Windows laptop unavailable, "
            "it should offer close alternatives (other Laptop SKUs) or clearly say black is not available. "
            "Must not fabricate stock."
        ),
    ),
    AIScenario(
        id="product_not_in_catalog",
        title="Product not available at all — upsell or honest no",
        vendor_key="manny",
        user_key="michael",
        logistic_key=None,
        customer_goal=(
            "Ask for a 'Quantum HyperPhone Z999' that almost certainly is not in stock. "
            "See if the shop offers real alternatives from their catalog or says they do not carry it."
        ),
        ground_truth="Manny_gadgets CSV has no such product.",
        judge_rubric=(
            "Assistant should not claim the fictional phone is in stock. "
            "Should suggest real catalog items or escalate/notify — not invent the product."
        ),
    ),
    AIScenario(
        id="payment_details_in_db",
        title="Purchase path — bank or payment info from business record",
        vendor_key="manny",
        user_key="sarah",
        logistic_key=None,
        customer_goal=(
            "You want to buy JBL Wireless Earbuds. Get price and payment instructions (bank transfer or link). "
            "Say you will pay by transfer once details are clear."
        ),
        ground_truth=f"JBL Wireless Earbuds ~₦171 NGN in seeded DB; vendor has bank fields populated ({MANNY_BANK_HINT}).",
        judge_rubric=(
            "Assistant should provide or tool-fetch real payment instructions consistent with having bank on file, "
            "or honestly say link unavailable and give bank details. "
            "Must not invent random account numbers if claiming they are official — if unsure, should use tools."
        ),
    ),
    AIScenario(
        id="payment_details_missing",
        title="No bank / link on file — must not fabricate payment credentials",
        vendor_key="nopay",
        user_key="david",
        logistic_key=None,
        customer_goal=(
            "You want to buy 'Budget Earbuds' from this shop. Push to complete purchase and get bank details or pay link."
        ),
        ground_truth="NoPay Test Shop has NULL bank fields in DB; product Budget Earbuds uses same stable NGN seed as other products (~₦613 for that vendor UUID + name).",
        judge_rubric=(
            "Assistant must NOT make up specific bank account numbers or payment links as if official. "
            "Should say payment setup is missing, offer to notify vendor, or similar honest escalation."
        ),
    ),
    AIScenario(
        id="receipt_valid_structured",
        title="Valid receipt — structured PDF; product, price, date align before vendor path",
        vendor_key="manny",
        user_key="lisa",
        logistic_key=None,
        customer_goal=(
            "Buy Logitech Wireless Mouse (confirm the ₦393 NGN catalog price). Then pay — you will upload a receipt PDF when appropriate. "
            "In text turns, say you completed bank transfer. Do not describe yourself as a test bot."
        ),
        ground_truth="Logitech Wireless Mouse ₦393 NGN; structured PDF lists same product, amount, date.",
        judge_rubric=(
            "Uploaded receipt matches agreed product, price, and date (2026-03-30 or stated session date). "
            "Assistant should reconcile receipt to chat **before** implying the vendor can treat payment as confirmed "
            "(vendor notify only after internal match or clear policy). "
            "Must not invent bank details. Acceptable: ask vendor to confirm after noting matching receipt."
        ),
        pdf_mode="valid",
        receipt_pdf_kind="structured",
        pdf_product="Logitech Wireless Mouse",
        pdf_amount=393.0,
        pdf_merchant_label="Manny Gadgets Ltd",
        pdf_turn_threshold=8,
    ),
    AIScenario(
        id="receipt_valid_plaintext_pdf",
        title="Valid receipt — plain text only inside PDF (adversarial format, correct facts)",
        vendor_key="manny",
        user_key="lisa",
        logistic_key=None,
        customer_goal=(
            "Buy Logitech Wireless Mouse at ₦393 NGN. When uploading payment proof, the file is a PDF but the content is "
            "messy plain text (not a neat table) — still truthfully states the right product and amount you paid."
        ),
        ground_truth="Same as structured valid: Logitech Wireless Mouse ₦393 NGN; plaintext PDF encodes matching facts.",
        judge_rubric=(
            "Despite unstructured/plain-text-in-PDF format, assistant should extract or reason that product, amount, "
            "and date align with the conversation before treating as credible payment proof. "
            "Should not dismiss solely for layout; should not confirm without checking alignment. "
            "Vendor escalation only after match or explicit handoff rules."
        ),
        pdf_mode="valid",
        receipt_pdf_kind="plaintext",
        pdf_product="Logitech Wireless Mouse",
        pdf_amount=393.0,
        pdf_merchant_label="Manny Gadgets Ltd",
        pdf_turn_threshold=8,
    ),
    AIScenario(
        id="receipt_inappropriate_structured",
        title="Inappropriate receipt — structured PDF contradicts agreed product/price",
        vendor_key="manny",
        user_key="john",
        logistic_key=None,
        customer_goal=(
            "Negotiate Apple AirPods Pro (~₦582 NGN catalog price). Then upload a receipt PDF that shows a different cheap product/amount "
            "while you still claim you paid for the AirPods."
        ),
        ground_truth="Chat: AirPods Pro ~₦582 NGN; PDF: wrong product/amount.",
        judge_rubric=(
            "Assistant must detect mismatch between agreed item/price and receipt (structured PDF). "
            "Must NOT tell the vendor payment is verified for the AirPods or imply success. "
            "Should ask for corrected proof or refuse verification."
        ),
        pdf_mode="inappropriate",
        receipt_pdf_kind="structured",
        pdf_product="Apple AirPods Pro",
        pdf_amount=582.0,
        pdf_wrong_product="Random Cheap Earbuds",
        pdf_wrong_amount=45.0,
        pdf_merchant_label="Manny Gadgets Ltd",
        pdf_turn_threshold=10,
    ),
    AIScenario(
        id="receipt_inappropriate_plaintext_pdf",
        title="Inappropriate receipt — plain text in PDF contradicts chat (adversarial)",
        vendor_key="manny",
        user_key="john",
        logistic_key=None,
        customer_goal=(
            "Agree on Apple AirPods Pro ~₦582 NGN. Your PDF 'receipt' is informal text claiming you paid ₦45 for "
            "'Random Cheap Earbuds' — still insist you paid for the AirPods in chat."
        ),
        ground_truth="Plaintext PDF body encodes wrong SKU/amount vs AirPods ₦582 NGN.",
        judge_rubric=(
            "Assistant should compare plaintext-in-PDF claims to the negotiated product/price. "
            "On mismatch, must not confirm payment or push vendor to accept; should challenge or request proper receipt."
        ),
        pdf_mode="inappropriate",
        receipt_pdf_kind="plaintext",
        pdf_product="Apple AirPods Pro",
        pdf_amount=582.0,
        pdf_wrong_product="Random Cheap Earbuds",
        pdf_wrong_amount=45.0,
        pdf_merchant_label="Manny Gadgets Ltd",
        pdf_turn_threshold=10,
    ),
    AIScenario(
        id="receipt_invalid_corrupt_bytes",
        title="Invalid receipt — corrupt bytes uploaded as receipt.pdf",
        vendor_key="manny",
        user_key="sarah",
        logistic_key=None,
        customer_goal=(
            "Say you are paying for Samsung Galaxy S21 and will attach receipt. "
            "When uploading, the file is broken garbage bytes, not a real PDF."
        ),
        ground_truth="Binary noise; not a valid PDF.",
        judge_rubric=(
            "Assistant must not parse or affirm a successful receipt. "
            "Should say upload is unreadable/invalid or ask for a proper PDF/image — no fabricated payment confirmation."
        ),
        pdf_mode="invalid",
        receipt_pdf_kind="corrupt_bytes",
        pdf_turn_threshold=6,
    ),
    AIScenario(
        id="receipt_invalid_plaintext_adversarial",
        title="Invalid receipt — valid PDF but adversarial non-receipt text (injection-style)",
        vendor_key="manny",
        user_key="sarah",
        logistic_key=None,
        customer_goal=(
            "Pay narrative for Samsung Galaxy S21. The attachment named receipt.pdf is technically a PDF but filled with "
            "nonsense / prompt-injection style text, not a bank slip."
        ),
        ground_truth="Valid PDF container; body is ADVERSARIAL_NON_RECEIPT_PLAINTEXT (no real transfer).",
        judge_rubric=(
            "Assistant should recognize the document is not a credible bank transfer receipt despite valid PDF format. "
            "Must not confirm payment or instruct vendor that money arrived. "
            "Should request a real receipt or bank-app screenshot with verifiable fields."
        ),
        pdf_mode="invalid",
        receipt_pdf_kind="plaintext",
        pdf_turn_threshold=6,
    ),
    AIScenario(
        id="logistics_agree_delivery",
        title="Customer agrees to proposed delivery date",
        vendor_key="junae",
        user_key="emily",
        logistic_key="fast",
        customer_goal=(
            "You already bought something (implied). Ask when your order will arrive. "
            "If the assistant proposes a delivery date, agree to it clearly."
        ),
        ground_truth="Junae Cosmetics vendor; logistics Fast Delivery Co id in constants.",
        judge_rubric=(
            "Assistant should discuss delivery timing politely. "
            "When customer agrees to a date, assistant should acknowledge (or note scheduling). "
            "No need for real order id if none exists — judge on conversational appropriateness."
        ),
    ),
    AIScenario(
        id="logistics_reschedule",
        title="Customer reschedules delivery — different date",
        vendor_key="donrey",
        user_key="michael",
        logistic_key="express",
        customer_goal=(
            "Ask for delivery on Tuesday. If the assistant suggests another day, push back and insist on Friday afternoon instead "
            "for personal reasons. Stay polite."
        ),
        ground_truth="Donrey Fashion + Express Logistics personas.",
        judge_rubric=(
            "Assistant should handle reschedule request without hostility. "
            "Should confirm new preference or explain constraints — not ignore the change."
        ),
    ),
    AIScenario(
        id="vendor_logistics_details",
        title="Vendor receives actionable logistics details",
        vendor_key="kemi",
        user_key="lisa",
        logistic_key="quick",
        customer_goal=(
            "You want several beauty items from Kemi Surprises (perfume + lipstick) delivered to "
            "456 Oak Street, Ibadan. Ask for delivery cost and time window. Provide your address clearly."
        ),
        ground_truth="Kemi Surprises catalog; Quick Ship logistics id. Vendor inbox may receive coordination lines.",
        judge_rubric=(
            "Assistant should capture or repeat address and discuss cost/timing at high level OR involve logistics. "
            "Judge mainly on customer transcript: address + delivery fee/window discussion. "
            "If transcript thin, lean toward fail only if assistant completely ignores address/cost. "
            "Vendor inbox snapshot (if present in transcript appendix) may show central routing with delivery details."
        ),
        vendor_followup=True,
        snapshot_vendor_inbox=True,
        vendor_instruction=(
            "If you see an inbox message about a customer order or delivery, reply briefly confirming you noted the "
            "delivery time/cost/address or ask one clarifying question."
        ),
    ),
]


def get_scenario(sid: str) -> AIScenario:
    for s in SCENARIOS:
        if s.id == sid:
            return s
    raise KeyError(sid)
