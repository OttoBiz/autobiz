"""
PDF receipt generation for payment verification tests.
Uses reportlab if available, otherwise falls back to a plain-text file
that the backend's LLM can still read and interpret.
"""
from datetime import date, timedelta
from io import BytesIO
from typing import Callable, Optional, Tuple


def _try_reportlab(draw_fn) -> Optional[bytes]:
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        buf = BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        draw_fn(c, A4)
        c.save()
        return buf.getvalue()
    except ImportError:
        return None


def generate_valid_receipt(
    vendor_name: str,
    product_name: str,
    amount: float,
    transaction_ref: str,
    payment_date: Optional[date] = None,
) -> Tuple[bytes, str]:
    """
    Generate a valid payment receipt that matches the expected product/amount/vendor.
    Returns (file_bytes, filename).
    """
    if payment_date is None:
        payment_date = date.today()

    fields = [
        ("Vendor:", vendor_name),
        ("Product:", product_name),
        ("Amount Paid:", f"NGN {amount:,.2f}"),
        ("Transaction Reference:", transaction_ref),
        ("Payment Date:", payment_date.strftime("%Y-%m-%d")),
        ("Status:", "PAYMENT CONFIRMED"),
        ("Bank:", "GTBank"),
    ]

    def draw(c, pagesize):
        from reportlab.lib.pagesizes import A4
        width, height = pagesize
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width / 2, height - 70, "PAYMENT RECEIPT")
        c.setFont("Helvetica", 10)
        c.drawCentredString(width / 2, height - 90, "This receipt confirms your payment.")
        y = height - 140
        for label, value in fields:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(80, y, label)
            c.setFont("Helvetica", 12)
            c.drawString(230, y, value)
            y -= 28
        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(width / 2, 60, "Thank you for your purchase.")

    pdf_bytes = _try_reportlab(draw)
    if pdf_bytes:
        return pdf_bytes, "payment_receipt.pdf"

    # Plain-text fallback
    lines = ["PAYMENT RECEIPT", "=" * 40]
    for label, value in fields:
        lines.append(f"{label} {value}")
    lines.append("=" * 40)
    return "\n".join(lines).encode(), "payment_receipt.txt"


def generate_invalid_receipt(
    vendor_name: str,
    product_name: str,
    correct_amount: float,
    transaction_ref: str,
) -> Tuple[bytes, str]:
    """
    Generate a receipt with mismatched details:
    - Amount is wrong (10× the actual price)
    - Date is 6 months in the past
    Returns (file_bytes, filename).
    """
    wrong_amount = correct_amount * 10
    wrong_date = date.today() - timedelta(days=180)

    fields = [
        ("Vendor:", vendor_name),
        ("Product:", product_name),
        ("Amount Paid:", f"NGN {wrong_amount:,.2f}"),   # wrong amount
        ("Transaction Reference:", transaction_ref),
        ("Payment Date:", wrong_date.strftime("%Y-%m-%d")),  # old date
        ("Status:", "PAYMENT CONFIRMED"),
        ("Bank:", "Access Bank"),
    ]

    def draw(c, pagesize):
        width, height = pagesize
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width / 2, height - 70, "PAYMENT RECEIPT")
        y = height - 140
        for label, value in fields:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(80, y, label)
            c.setFont("Helvetica", 12)
            c.drawString(230, y, value)
            y -= 28

    pdf_bytes = _try_reportlab(draw)
    if pdf_bytes:
        return pdf_bytes, "payment_receipt_wrong.pdf"

    lines = ["PAYMENT RECEIPT", "=" * 40]
    for label, value in fields:
        lines.append(f"{label} {value}")
    lines.append("=" * 40)
    return "\n".join(lines).encode(), "payment_receipt_wrong.txt"


def generate_inappropriate_document() -> Tuple[bytes, str]:
    """
    Generate a document that is clearly NOT a payment receipt (a CV / job application).
    Returns (file_bytes, filename).
    """
    def draw(c, pagesize):
        width, height = pagesize
        c.setFont("Helvetica-Bold", 20)
        c.drawCentredString(width / 2, height - 70, "CURRICULUM VITAE")
        y = height - 130
        items = [
            "Name: Chukwuemeka Obi",
            "Email: chukwuemeka.obi@gmail.com",
            "Phone: +234 801 234 5678",
            "",
            "OBJECTIVE",
            "Seeking a challenging role in sales and marketing at a reputable organisation.",
            "",
            "WORK EXPERIENCE",
            "Sales Associate — NextGen Retail (2020-2023)",
            "  • Managed customer relations and product promotions",
            "  • Achieved 120% of quarterly sales targets",
            "",
            "EDUCATION",
            "B.Sc Business Administration — University of Lagos (2019)",
            "",
            "SKILLS",
            "Microsoft Office, Customer Service, Inventory Management",
        ]
        c.setFont("Helvetica", 11)
        for item in items:
            c.drawString(60, y, item)
            y -= 20

    pdf_bytes = _try_reportlab(draw)
    if pdf_bytes:
        return pdf_bytes, "cv_document.pdf"

    content = """CURRICULUM VITAE
Name: Chukwuemeka Obi
Objective: Seeking a challenging sales role.
Experience: Sales Associate at NextGen Retail (2020-2023)
Education: B.Sc Business Administration, University of Lagos (2019)"""
    return content.encode(), "cv_document.txt"


