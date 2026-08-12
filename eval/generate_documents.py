"""Deterministic generator for the Phase 10 eval seed PDFs (docs/testing.md §6).

Builds the made-up company policy pack (Acme Supply Co.) into
`eval/documents/`: refund-policy.pdf, shipping-policy.pdf, hr-handbook.pdf -
short pages with unambiguous facts and *known page numbers* so
`eval/datasets/qa.json` can pin `expected_page`. Re-running this script
produces byte-identical PDFs (stdlib only, deterministic content streams and
xref table), so the seed corpus is reproducible on a clean checkout.

The minimal PDF writer mirrors `backend/tests/pdf_fixtures.py` (research.md
R7): one content stream per page, one `Tj` op per wrapped line, correct xref
table. Imported from end-to-end tests but intentionally self-contained here so
the eval corpus does not depend on test module internals.
"""

from __future__ import annotations

import pathlib
import textwrap

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "eval" / "documents"

_LINE_WIDTH = 92
_LINE_HEIGHT = 15
_TOP_MARGIN = 740

# filename -> pages (1-indexed; page text is one paragraph, wrapped at render).
# Facts and phrasings are deliberately unambiguous and answer queries in
# eval/datasets/qa.json. Every `answer_contains` string must appear verbatim
# (case-insensitively) on its `expected_page`.
PAGES: dict[str, list[str]] = {
    "refund-policy.pdf": [
        # 1
        "Acme Supply Co. - Refund & Return Policy. Effective January 1, 2026. "
        "This policy explains how to return items bought from Acme Supply Co. "
        "and get a refund or an exchange. Please read it before you contact the "
        "support team.",
        # 2
        "When may I ask for a refund? All refund requests must be submitted within "
        "30 days of the original purchase date. Requests received after the 30-day "
        "window are declined unless the item arrived damaged or defective. You can "
        "submit the request through the Acme Support portal or by emailing "
        "support@acme.example.",
        # 3
        "Eligibility. To qualify for a refund the item must be in its original "
        "condition and in the original packaging. You must include the order number "
        "and the original receipt or the email confirmation. Items that show signs "
        "of use or missing packaging are not eligible for a refund.",
        # 4
        "Opening the box. A restocking fee of 15% applies to opened items that are "
        "returned for a refund. Unopened items in the original packaging are "
        "refunded in full with no fee. The restocking fee is deducted from the "
        "refund amount before it is issued.",
        # 5
        "What cannot be returned. Perishable items, consumables, and downloadable "
        "software are not refundable. Custom or personalized products are also "
        "non-refundable. Gift cards cannot be returned or exchanged.",
        # 6
        "How refunds are paid. Refunds are issued to the original payment method. "
        "If you return an item without a receipt, you will receive store credit "
        "instead. Store credit never expires and can be used for any Acme product.",
        # 7
        "Processing time. Once we receive and inspect your return, the refund is "
        "issued within 5 business days. The refund appears on your statement within "
        "5 to 10 business days of the issuing date. You will receive an email "
        "confirming the refund amount.",
        # 8
        "Return shipping. We email a prepaid return shipping label within 2 "
        "business days of approval. The label covers standard ground shipping. For "
        "returns from outside the United States the label cost is deducted from "
        "your refund.",
        # 9
        "Gift receipts. If the item was a gift, refunds are issued as store credit "
        "in the amount of the gift purchase price. The credit is sent to the gift "
        "recipient. The recipient can use it on any Acme Supply Co. order.",
        # 10
        "Warranty claims. This policy is separate from the limited warranty. The "
        "limited warranty covers defects for 90 days from the date of delivery. "
        "Warranty claims are handled by the Acme repairs team, not the refund team.",
        # 11
        "Damaged or defective items. If your item arrived damaged or defective, we "
        "offer a replacement or a full refund. No restocking fee applies to damaged "
        "or defective returns. Please include photos of the damage with your "
        "request.",
        # 12
        "How to request a refund. Open the Acme Support portal and choose Return or "
        "Refund. You must submit the request within the refund window and include "
        "your order number. Our team responds within one business day.",
        # 13
        "Chargebacks. If you dispute a charge with your credit card company before "
        "contacting us, the dispute is treated as a chargeback. Repeated chargebacks "
        "on an account lead to account suspension. Contact us first and we will "
        "resolve the issue.",
        # 14
        "Policy changes. Acme Supply Co. may update this refund policy at any time. "
        "Updates are posted on this page and take effect on the date they are posted. "
        "The policy that applies to your order is the one in effect on the purchase "
        "date. Contact: support@acme.example or 1-800-555-0142.",
    ],
    "shipping-policy.pdf": [
        # 1
        "Acme Supply Co. - Shipping & Delivery Policy. Effective January 1, 2026. "
        "This policy explains how orders are packed, shipped, and delivered by Acme "
        "Supply Co. Delivery times start once an order has been packed and handed "
        "to the carrier.",
        # 2
        "Processing time. Orders are processed and shipped within 2 business days "
        "of order confirmation. Orders placed on weekends ship on the next business "
        "day. You receive a confirmation email as soon as your order ships.",
        # 3
        "Standard delivery. Standard shipping is delivered in 5-7 business days "
        "across the United States via UPS Ground. Standard delivery is free for "
        "orders over $50. Deliveries to Alaska, Hawaii, and Puerto Rico may take an "
        "additional 3 business days.",
        # 4
        "Express shipping. Express delivery is available for orders placed before "
        "2pm local time and arrives the next business day. Express is offered only "
        "for addresses within the United States. The express fee is calculated at "
        "checkout.",
        # 5
        "International shipping. We ship internationally to select countries. "
        "International deliveries take 10-15 business days from the shipping date. "
        "Import duties and taxes are charged at the destination and are not "
        "included in the order total.",
        # 6
        "Free shipping. Orders over $50 ship free with standard ground delivery. "
        "The $50 threshold is calculated on the pre-tax order subtotal. Free "
        "shipping is not available for international orders.",
        # 7
        "Tracking. A tracking number is emailed to you the day your order ships. "
        "The tracking email contains a link to the carrier's site. Tracking is "
        "updated within 24 hours of the carrier receiving the package.",
        # 8
        "Address changes. You may change the delivery address within 12 hours of "
        "placing the order. After 12 hours the package is prepared for shipping and "
        "the address can no longer be changed. Contact support promptly if you need "
        "an address change.",
        # 9
        "Undeliverable packages. If the carrier cannot deliver a package, we make "
        "3 delivery attempts. After 3 failed attempts the package is returned to our "
        "warehouse. The return shipping cost is deducted from your refund.",
        # 10
        "Delivery exceptions. Weather, holidays, and carrier outages can delay "
        "delivery. Acme Supply Co. does not guarantee exact delivery dates during "
        "peak seasons. Signatures are required for orders over $200.",
        # 11
        "P.O. boxes and APO addresses. We ship to P.O. boxes and APO addresses with "
        "standard shipping only. Express shipping is not available for P.O. boxes. "
        "Packages to APO addresses use the military postal service.",
        # 12
        "Lost or stolen packages. If a package has not arrived within 7 business "
        "days of the estimated delivery date, contact support to file a claim. "
        "Claims for lost packages are reviewed by the shipment team. We do not "
        "refund perishable items once shipped.",
        # 13
        "Shipping insurance. Every package includes $100 of shipping insurance at "
        "no cost. Additional coverage up to $2,500 can be purchased at checkout. "
        "Claims are filed through the Acme Support portal.",
        # 14
        "Policy changes. Acme Supply Co. may update this shipping policy at any "
        "time. Updates take effect when posted on this page. This policy applies to "
        "orders placed from the date it is posted. Contact: shipping@acme.example "
        "or 1-800-555-0142.",
    ],
    "benefits-policy.pdf": [
        # 1
        "Acme Supply Co. Benefits Program. Effective January 1, 2026. This policy "
        "describes the benefits available to Acme employees: health, dental, "
        "vision, life insurance, retirement, and more. Enrollment happens through "
        "the People Ops portal.",
        # 2
        "Health insurance plans. Acme offers three health insurance plans: HMO, "
        "PPO, and a high-deductible plan. The PPO plan has a $1,500 individual "
        "deductible. Preventive care is covered at 100% on every plan. Enrollment "
        "timelines are in the Employee Handbook.",
        # 3
        "Dental coverage. Dental coverage includes two cleanings and one exam per "
        "year at no cost. Orthodontia for dependents is covered at 50% up to a "
        "$1,500 lifetime maximum. Dental care for adults has a $2,000 annual "
        "maximum.",
        # 4
        "Vision coverage. Vision coverage includes one eye exam every 12 months. "
        "Eyeglass frames are covered up to $150 every 24 months. Contact lenses "
        "are covered up to $250 per year.",
        # 5
        "Life insurance. Every full-time employee receives group life insurance "
        "equal to 1x annual salary, paid by Acme, up to $250,000. You may buy "
        "additional coverage up to 5x salary at group rates.",
        # 6
        "Disability insurance. Short-term disability pays 60% of salary for up to "
        "6 months. Long-term disability pays 60% of salary until age 65 after 6 "
        "months of disability. Enroll within 31 days of hire.",
        # 7
        "Flexible spending accounts. A health care FSA lets you set aside up to "
        "$3,050 pre-tax per year. A dependent care FSA allows up to $5,000 per "
        "household. Unused FSA funds are forfeited at year-end.",
        # 8
        "Parental leave. New parents receive 12 weeks of paid parental leave. "
        "Parental leave can be taken at 70% pay or spread across 20 weeks at 60% "
        "pay. Acme also offers a return-to-work transition program.",
        # 9
        "Wellness stipend. Acme offers a $600 annual wellness stipend for gym "
        "memberships and wellness programs. The stipend is paid as a "
        "reimbursement, not a taxable allowance. Wellness reimbursements are "
        "submitted through People Ops.",
        # 10
        "Tuition reimbursement. Tuition reimbursement covers up to $5,250 per year "
        "for approved courses. Reimbursement requires a passing grade and a signed "
        "learning agreement. Textbooks and fees are also covered.",
        # 11
        "Commuter benefits. The commuter benefit allows pre-tax deductions for "
        "transit passes up to $315 per month. Parking is reimbursed up to $100 per "
        "month. Commuter cards are issued on the first business day of each month.",
        # 12
        "Employee assistance program. The Employee Assistance Program provides 8 "
        "free counseling sessions per issue, per year. The EAP is confidential and "
        "available 24/7 by phone. Dependent family members may also use the EAP.",
        # 13
        "Plan changes. Benefits change during annual open enrollment, which runs "
        "every November. Contact benefits@acme.example with questions. This policy "
        "does not create a contract of employment.",
    ],
    "data-security-policy.pdf": [
        # 1
        "Acme Supply Co. Data Security Policy. Effective January 1, 2026. This "
        "policy states how Acme protects company data and customer data. Every "
        "employee is responsible for following it.",
        # 2
        "Passwords. Work accounts require a password of at least 12 characters "
        "and MFA. Passwords rotate every 90 days. Never reuse a personal password "
        "on a work account.",
        # 3
        "Phishing. Report suspicious email to security@acme.example. Never click "
        "links in unexpected messages. Acme runs simulated phishing tests each "
        "quarter.",
        # 4
        "Encryption. All company laptops are encrypted with full-disk encryption. "
        "Company data is encrypted at rest and in transit. USB drives are not "
        "permitted for company data.",
        # 5
        "Data classification. Acme uses three data classes: public, internal, and "
        "confidential. Confidential data includes customer lists and unannounced "
        "products. Confidential data requires the highest protection.",
        # 6
        "Remote access. Remote access requires the company VPN plus MFA. Work "
        "devices use a zero-trust posture with least-privilege access by default. "
        "Personal devices are allowed only with approved management software.",
        # 7
        "Incident reporting. Report any suspected breach within 1 hour to "
        "security@acme.example. Do not discuss incidents outside the security team "
        "until approved. Acme protects reporters from retaliation.",
        # 8
        "Clean desk. Lock screens when you step away from your desk. Remove "
        "sensitive documents from desks overnight. Badges must be worn in the "
        "office.",
        # 9
        "Third parties. Vendors must sign a data processing agreement before "
        "accessing Acme data. Vendor access is reviewed twice a year. Contractors "
        "complete the same security training as employees.",
        # 10
        "Policy changes. Acme may update this policy at any time. Contact "
        "security@acme.example with questions. Violations may result in "
        "disciplinary action, up to termination.",
    ],
    "hr-handbook.pdf": [
        # 1
        "Acme Supply Co. - Employee Handbook. Effective January 1, 2026. This "
        "handbook describes the policies, benefits, and expectations that apply to "
        "every Acme Supply Co. employee. Please read the whole handbook and ask "
        "People Ops if anything is unclear.",
        # 2
        "Employment at will. Employment with Acme Supply Co. is at-will. Either you "
        "or the company may end the employment relationship at any time, with or "
        "without cause or notice. Nothing in this handbook changes the at-will "
        "relationship.",
        # 3
        "Work hours. The standard workweek is 40 hours, Monday through Friday. "
        "Full-time staff work 8 hours per day. Flexible hours are available with "
        "approval from your manager.",
        # 4
        "Paid vacation. You accrue 10 days of paid vacation in your first year. "
        "Vacation accrues at 1 day per month for the first year. After 5 years of "
        "service the annual allowance rises to 15 days.",
        # 5
        "Sick leave. You receive 5 days of paid sick leave each calendar year. "
        "Unused sick days do not roll over to the next year. Sick leave is "
        "available after 30 days of employment.",
        # 6
        "Paid holidays. Acme observes 10 company holidays per year, including New "
        "Year's Day and Thanksgiving. Company holidays are paid days off for "
        "full-time staff. Part-time staff are paid only for holidays they work.",
        # 7
        "Health insurance. Medical, dental, and vision coverage begins after 90 "
        "days of full-time employment. The coverage premium is shared: the company "
        "pays 70% and you pay 30% of the premium. Enroll through the People Ops "
        "portal.",
        # 8
        "Retirement. Acme offers a 401(k) plan with a 4% company match. You are "
        "eligible after 1 year of employment. Contributions are deducted pre-tax "
        "on every pay period.",
        # 9
        "Expense reimbursement. Submit expense reports within 30 days of the "
        "expense date. Approved expenses are reimbursed by the next payroll cycle. "
        "Travel expenses above $500 need manager approval before booking.",
        # 10
        "Code of conduct. Acme prohibits discrimination, harassment, and "
        "retaliation. Report any concern to People Ops or through the confidential "
        "hotline. No employee is punished for making a good-faith report.",
        # 11
        "Remote work. Remote arrangements are approved by your manager and require "
        "a security review. Remote employees must keep their devices encrypted and "
        "use the company VPN. Desk space is provided in the office for hybrid "
        "staff.",
        # 12
        "Performance reviews. Performance reviews are held twice per year, in June "
        "and December. Every review includes a self-assessment, a manager review, "
        "and a peer check. Review outcomes can affect promotion and compensation.",
        # 13
        "Notice of resignation. Employees who resign voluntarily are asked to give "
        "2 weeks' notice. Notice is submitted to your manager in writing. "
        "Unexcused absences during the notice period are counted against your final "
        "pay.",
        # 14
        "Confidential information. Employees must not disclose confidential company "
        "information without written authorization. Confidential information "
        "includes customer lists, pricing, and unannounced products. This duty "
        "continues after employment ends.",
        # 15
        "Leave of absence. Family and medical leave is available after 12 months of "
        "employment. Eligible employees receive up to 12 weeks of unpaid leave per "
        "year. Leave is protected by law for qualifying reasons.",
        # 16
        "Contact. For benefits questions contact People Ops at "
        "people-ops@acme.example or 1-800-555-0199. For payroll questions contact "
        "payroll@acme.example. This handbook is not a contract of employment.",
    ],
}


def _escape_pdf_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _build_pdf(objects: list[bytes], *, root: int = 1) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    count = len(objects) + 1
    out += f"xref\n0 {count}\n".encode()
    out += b"0000000000 65535 f \r\n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \r\n".encode()
    out += (
        f"trailer\n<< /Size {count} /Root {root} 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    ).encode()
    return bytes(out)


def _page_object(
    text: str, pages_ref: int, font_ref: int, page_index: int
) -> tuple[bytes, bytes]:
    """Content + page objects for one page (content object index known later)."""
    lines = textwrap.wrap(text, width=_LINE_WIDTH) or [text]
    ops: list[str] = []
    for offset, line in enumerate(lines):
        y = _TOP_MARGIN - offset * _LINE_HEIGHT
        ops.append(f"BT /F1 10 Tf 72 {y} Td ({_escape_pdf_string(line)}) Tj ET")
    stream = ("\n".join(ops)).encode()
    content_body = (
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream"
    )
    page_body = (
        f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 612 792] "
        f"/Contents {page_index + 1} 0 R /Resources << /Font << /F1 {font_ref} 0 R "
        f">> >> >>"
    ).encode()
    return content_body, page_body


def make_policy_pdf(pages: list[str]) -> bytes:
    """Build a single policy PDF with one page per entry (research.md R7)."""
    if not pages:
        raise ValueError("a policy PDF needs at least one page")
    # Object plan: 1 catalog, 2 font, 3 pages, then 2 objects per page
    # (page, content) alternating, content first to keep the page's ref stable.
    catalog_ref, font_ref, pages_ref = 1, 2, 3
    objects: list[bytes] = []
    content_bodies: list[bytes] = []
    page_bodies: list[bytes] = []
    for text in pages:
        content_body, page_body = _page_object(text, pages_ref, font_ref, len(page_bodies))
        content_bodies.append(content_body)
        page_bodies.append(page_body)
    objects.append(b"<< /Type /Catalog /Pages 3 0 R >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    kids = " ".join(
        f"{5 + 2 * index} 0 R" for index in range(len(page_bodies))
    )
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_bodies)} >>".encode())
    # Content object i sits at object 4 + 2*i; page i at 5 + 2*i.
    for index in range(len(page_bodies)):
        objects.append(content_bodies[index])
        page_body = page_bodies[index]
        page_body = page_body.replace(
            f"/Contents {index + 1} 0 R".encode(),  # placeholder from _page_object
            f"/Contents {4 + 2 * index} 0 R".encode(),
        )
        objects.append(page_body)
    return _build_pdf(objects, root=catalog_ref)


def generate() -> None:
    """Write eval/documents/*.pdf deterministically (byte-identical re-runs)."""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, pages in PAGES.items():
        data = make_policy_pdf(pages)
        out = DOCS_DIR / filename
        out.write_bytes(data)
        print(f"wrote {out} ({len(data)} bytes, {len(pages)} pages)")


if __name__ == "__main__":
    generate()