"""Independently authored nonbinding compute-services draft from a saved receipt.

No financial-market master agreement form, external assets, arbitrary HTML or
live data fetch is used. Monetary calculations belong to the evaluated model.
"""
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
from io import BytesIO
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from compute_pricing.control.domain import ValidationError, utc_instant
from compute_pricing.control.reporting.store import canonical_document

VERSION = "demo-compute-agreement/1.0.0"
MARKING = "NONBINDING - UNSIGNED - SIMULATED"
UNRESOLVED = "Unresolved / not supplied"
WIDTH = 504
INK = colors.HexColor("#172A35")
MUTED = colors.HexColor("#647379")
ACCENT = colors.HexColor("#205C54")
RULE = colors.HexColor("#DAE1E2")
TINT = colors.HexColor("#F4F6F5")


def _receipt(receipt):
    if not isinstance(receipt, Mapping) or set(receipt) != {"snapshot_id", "created_at", "document"}:
        raise ValidationError("agreement: saved snapshot envelope required")
    identity, created, document = receipt["snapshot_id"], receipt["created_at"], receipt["document"]
    if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{64}", identity):
        raise ValidationError("agreement: canonical receipt identifier required")
    utc_instant(created)
    if not isinstance(document, Mapping) or document.get("schema_version") != "compute-snapshot/1.0" or document.get("kind") != "demo_pricing":
        raise ValidationError("agreement: demo-pricing snapshot required")
    encoded = canonical_document(document, max_bytes=2 * 1024 * 1024)
    if hashlib.sha256(encoded.encode("utf-8")).hexdigest() != identity:
        raise ValidationError("agreement: receipt integrity mismatch")
    source, result = document.get("input"), document.get("output")
    if not isinstance(source, Mapping) or not isinstance(result, Mapping):
        raise ValidationError("agreement: evaluated input and result required")
    if result.get("classification") != "synthetic" or result.get("execution_enabled") is not False:
        raise ValidationError("agreement: synthetic nonexecuting evaluation required")
    if result.get("firm_price_eligible") is True or result.get("executable") is True:
        raise ValidationError("agreement: firm or executable documents unsupported")
    return identity, created, source, result, document.get("versions", {})


def _literal(value):
    if value is None:
        return UNRESOLVED
    if isinstance(value, bool):
        return "Yes - declared scenario" if value else "No - declared scenario"
    if not isinstance(value, (str, int)) or len(str(value)) > 512:
        raise ValidationError("agreement: bounded display value required")
    result = str(value).replace("\u2013", "-").replace("\u2014", "-").replace("\u2011", "-").replace("\u00a0", " ")
    if any(ord(char) < 32 for char in result):
        raise ValidationError("agreement: display control character forbidden")
    try:
        result.encode("cp1252")
    except UnicodeEncodeError:
        raise ValidationError("agreement: display character unsupported") from None
    return result


def _decimal(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 2048 or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value):
        raise ValidationError("agreement: exact financial display value required")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValidationError("agreement: financial display value invalid") from None
    if not amount.is_finite():
        raise ValidationError("agreement: financial display value invalid")
    return amount


def _money(value):
    amount = _decimal(value)
    if amount is None:
        return UNRESOLVED
    with localcontext() as context:
        context.prec = 160
        result = format(amount, ",.2f")
    if len(result) > 54:
        raise ValidationError("agreement: financial display budget exceeded")
    return "USD " + result


def _percent(value):
    amount = _decimal(value)
    if amount is None:
        return UNRESOLVED
    with localcontext() as context:
        context.prec = 160
        result = format(amount * 100, ",.2f") + "%"
    if len(result) > 54:
        raise ValidationError("agreement: financial display budget exceeded")
    return result


def _styles():
    common = {"fontName": "Helvetica", "textColor": INK, "alignment": TA_LEFT,
        "splitLongWords": True, "allowWidows": 0, "allowOrphans": 0}
    return {"body": ParagraphStyle("agreement-body", fontSize=9.1, leading=13.1, **common),
        "small": ParagraphStyle("agreement-small", fontSize=8, leading=11.4, **common),
        "value": ParagraphStyle("agreement-value", fontSize=8.7, leading=12, **common),
        "label": ParagraphStyle("agreement-label", fontSize=8.1, leading=11.5,
            **{**common, "textColor": MUTED}),
        "title": ParagraphStyle("agreement-title", fontSize=23, leading=26, spaceAfter=10,
            **{**common, "fontName": "Helvetica-Bold"}),
        "section": ParagraphStyle("agreement-section", fontSize=10, leading=13,
            spaceBefore=12, spaceAfter=7, **{**common, "fontName": "Helvetica-Bold"}),
        "clause": ParagraphStyle("agreement-clause", fontSize=8.8, leading=12.5,
            spaceAfter=8, **common)}


def _paragraph(value, style):
    return Paragraph(escape(_literal(value)), style)


def _table(rows, styles):
    values = [[_paragraph(label, styles["label"]), _paragraph(value, styles["value"])] for label, value in rows]
    table = Table(values, colWidths=[144, WIDTH - 144], hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 15),
        ("RIGHTPADDING", (1, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LINEBELOW", (0, 0), (-1, -1), .45, RULE)]))
    return table


def _section(story, styles, title, rows):
    story.extend([_paragraph(title, styles["section"]), _table(rows, styles)])


def _clause(story, styles, label, body):
    # The only markup is author-owned; source values are always escaped text.
    story.append(Paragraph("<b>" + escape(label) + "</b> " + escape(_literal(body)), styles["clause"]))


def _page(canvas, document, identity):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(.55)
    canvas.line(54, 742, 558, 742)
    canvas.setFillColor(ACCENT)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(54, 756, "COMPUTEBASIS / COMPUTE SERVICES DRAFT")
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.8)
    canvas.drawRightString(558, 756, MARKING)
    canvas.line(54, 45, 558, 45)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(54, 32, MARKING)
    canvas.drawRightString(558, 32, "Receipt " + identity[:12] + " / " + str(document.page) + " of 3")
    canvas.restoreState()


def _canvas(*args, **kwargs):
    return Canvas(*args, **{**kwargs, "invariant": 1})


def _group(terms, key):
    value = terms.get(key)
    if not isinstance(value, Mapping):
        raise ValidationError("agreement: evaluated schedule section required")
    return value


def _rate(value):
    amount = _decimal(value)
    if amount is None:
        return UNRESOLVED
    if len(value) <= 24:
        shown = value
    else:
        with localcontext() as context:
            context.prec = max(160, len(value) + 16)
            rounded = format(amount, ".6f").rstrip("0").rstrip(".")
            if amount and Decimal(rounded) == 0:
                rounded = format(amount, ".5E")
        if len(rounded) > 54:
            raise ValidationError("agreement: financial display budget exceeded")
        shown = "~" + rounded
    return "USD " + shown + " / GPU-hour"


def _party_label(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 160:
        raise ValidationError("agreement: explicit bounded evaluated party label required")
    return _literal(value)


def _words(value):
    return _literal(value).replace("_", " ").replace("ACT365", "ACT/365")


def _claims(value):
    # Known public scenario claims only, not arbitrary source/customer objects.
    if isinstance(value, Mapping):
        selected = []
        for key in ("soc2", "iso27001", "isolation", "data_residency", "data_retention", "training_use"):
            if key in value:
                selected.append(key.replace("_", " ") + ": " + _literal(value[key]))
        return "; ".join(selected) if selected else UNRESOLVED
    if isinstance(value, str) or value is None or type(value) is bool:
        return _literal(value)
    return UNRESOLVED


def _shared_yield(settlement):
    return "; ".join(label + " " + _percent(settlement.get("yield_share_" + key))
        for key, label in (("provider", "Supplier"), ("broker", "Broker"), ("buyer", "Buyer")))


def _schedule(story, styles, terms):
    capacity, pricing = _group(terms, "capacity"), _group(terms, "pricing")
    provider = _group(terms, "provider")
    settlement = _group(terms, "settlement")
    counts = (capacity.get("gpus_per_node"), capacity.get("node_count"))
    if any(type(value) is not int or not 1 <= value <= 1000000 for value in counts):
        raise ValidationError("agreement: explicit whole nodes and GPUs per node required")
    if capacity.get("total_gpu_count") != counts[0] * counts[1]:
        raise ValidationError("agreement: evaluated whole-GPU allocation mismatch")
    if pricing.get("currency") != "USD" or pricing.get("price_unit") != "gpu_hour":
        raise ValidationError("agreement: explicit supported currency and native rate unit required")
    story.append(_paragraph("Compute services\nquote schedule".replace("\n", " / "), styles["title"]))
    story.append(_paragraph("Schedule 01 / Proposed commercial terms for an evaluated demonstration", styles["small"]))
    story.append(Spacer(1, 10))
    story.append(_paragraph("This unsigned draft describes simulated capacity and modeled economics. It becomes no service commitment, purchase, financing or legal entitlement.", styles["body"]))
    _section(story, styles, "Parties and roles", [
        ("Supplier", _party_label(provider.get("label")) + " - declared, identity unverified"),
        ("Buyer / broker", _party_label(settlement.get("buyer_label")) + " / Demo Compute Broker - declared roles"),
        ("Supply ownership", capacity.get("ownership"))])
    _section(story, styles, "Capacity and delivery", [
        ("Hardware", _literal(capacity.get("model")) + " / memory " + _literal(capacity.get("memory_gib")) + " GiB per device"),
        ("Whole allocation", str(counts[1]) + (" node x " if counts[1] == 1 else " nodes x ") + str(counts[0]) + " GPUs = " + str(counts[0] * counts[1]) + " GPUs"),
        ("Service location", _literal(capacity.get("country_code")) + " / " + _literal(capacity.get("location"))),
        ("Colocation assumption", capacity.get("colocation")),
        ("Service begins / ends", _literal(capacity.get("starts_at")) + " / " + _literal(capacity.get("ends_at")))])
    _section(story, styles, "Price and billing basis", [
        ("Supplier service rate", _rate(pricing.get("supplier_rate"))),
        ("Price convention", _literal(pricing.get("rate_type")) + "; variable low/high " + _rate(pricing.get("variable_low")) + " / " + _rate(pricing.get("variable_high"))),
        ("Proposed buyer rate", _rate(pricing.get("buyer_rate"))),
        ("Utilization / collection", _percent(pricing.get("billed_utilization")) + " billed; " + _percent(pricing.get("collection_share")) + " collected - modeled"),
        ("Fees and owned costs", _percent(pricing.get("fee_on_collected")) + " of collections; " + _percent(pricing.get("fee_on_gross")) + " of gross; " + _money(pricing.get("fixed_operating_cost")) + " fixed operations"),
        ("Credit context", _literal(provider.get("credit_score")) + " score / " + _literal(provider.get("credit_band")) + " band - simulated, uncalibrated")])


def _operating_terms(story, styles, terms):
    provider, pricing = _group(terms, "provider"), _group(terms, "pricing")
    settlement = _group(terms, "settlement")
    power = pricing.get("power") if isinstance(pricing.get("power"), Mapping) else {}
    story.append(_paragraph("Draft master agreement", styles["title"]))
    story.append(_paragraph("Schedule 01 controls the simulated service scope; legal execution remains unresolved.", styles["small"]))
    _section(story, styles, "Service levels and ownership declarations", [
        ("Availability / SLA", _percent(provider.get("uptime_fraction")) + " declared uptime; " + _percent(provider.get("sla_fraction")) + " proposed SLA"),
        ("Response / remedy", _literal(provider.get("response_hours")) + (" hour" if provider.get("response_hours") == "1" else " hours") + "; service-credit remedy and liability cap unresolved"),
        ("Compliance / privacy", _claims(provider.get("compliance")) + " / " + _claims(provider.get("privacy"))),
        ("Power model / payer", _literal(power.get("cost_owner")) + " model; legal payer " + _literal(power.get("payer")) + "; " + _literal(power.get("inclusion")) + " in supplier price - no duplicate all-in charge"),
        ("Risk allowance", _rate(pricing.get("risk_allowance_per_gpu_hour")) + " - scenario-owned allowance, not a guaranteed loss estimate")])
    story.append(Spacer(1, 12))
    _clause(story, styles, "1. Service scope.", "The proposed Supplier would furnish only the scheduled capacity during the stated UTC window. This draft verifies no inventory, GPU performance, topology or capacity reservation.")
    _clause(story, styles, "2. Price and changes.", "The declared fixed or variable convention controls this scenario. Benchmark resets, taxes, egress, index fallback and a binding rate-change procedure require separate agreed terms.")
    _clause(story, styles, "3. Power and colocation.", "The stated model owns the power calculation, not legal payment responsibility. The payer and site meter evidence require agreement. Included power must not be charged twice in an all-in supplier rate.")
    _clause(story, styles, "4. Service evidence and data.", "Uptime, response and compliance statements are simulated claims. Acceptance tests, incident reporting, data isolation, retention, security schedules and remedies require definitive evidence and approval.")
    _clause(story, styles, "5. Credit protection.", "Prepayment exposure, collateral and escrow are different balances. A modeled credit band creates no security interest, bank guarantee, custody right, insured deposit or liquidation authority.")
    _clause(story, styles, "6. Vesting and yield.", "Only the stated service basis and release assumption may vest simulated principal. Accrued yield, spendable cash and party entitlements remain separate; neither yield nor a deposit is service revenue by default.")
    _clause(story, styles, "7. Termination and disputes.", "Termination rights, refunds, insolvency treatment, liability limits, governing law, courts, tax allocation and authorized signatures remain unresolved. No party may treat this file as an executed agreement.")
    story.append(Spacer(1, 6))
    story.append(_paragraph("Declared settlement mode: " + _literal(settlement.get("mode")) + ". Governing law: UNRESOLVED. Signature authority: UNRESOLVED. Signatures: NOT EXECUTED.", styles["small"]))


def _economic_supplement(story, styles, terms, identity, created, versions):
    settlement, treasury = _group(terms, "settlement"), _group(terms, "treasury")
    summary = _group(terms, "summary")
    dates = treasury.get("payment_dates") if isinstance(treasury.get("payment_dates"), Mapping) else treasury
    mode = settlement.get("mode")
    escrow_application = ("Active simulated hourly service escrow" if mode == "hourly_escrow" else
        "Inactive in milestone mode; escrow/yield inputs do not create a contract" if mode == "milestone" else
        "Applicability unresolved; declared inputs only")
    story.append(_paragraph("Settlement and economics", styles["title"]))
    story.append(_paragraph("Schedule 01 supplement / Rounded USD totals; ~ marks approximate rates. Exact values remain in the receipt.", styles["small"]))
    _section(story, styles, "Funding, collateral and release", [
        ("Escrow applicability", escrow_application),
        ("Supplier prepayment", _percent(settlement.get("down_payment_fraction")) + "; financing APR " + _percent(settlement.get("financing_apr"))),
        ("Supplier / buyer cash dates", "Initial " + _literal(dates.get("supplier_payment_on")) + "; balance " + _literal(dates.get("supplier_balance_on")) + "; buyer invoice " + _literal(dates.get("buyer_invoice_on")) + "; receipt " + _literal(dates.get("buyer_receipt_on"))),
        ("Principal / asset", _literal(settlement.get("prefunded_principal")) + " " + _literal(settlement.get("asset_unit")) + "; " + _words(settlement.get("asset_kind")) + "; USD/unit " + _literal(settlement.get("asset_price_usd"))),
        ("Collateral ownership", _money(settlement.get("provider_collateral_usd")) + " / " + _words(settlement.get("collateral_owner"))),
        ("Vesting / access", _words(settlement.get("vesting_basis")) + "; " + _literal(settlement.get("liquidity")) + "; depeg " + _words(settlement.get("depeg_status"))),
        ("Release / refund", _literal(settlement.get("release_authorized")) + " / " + _literal(settlement.get("refund_at_end")) + "; buffer " + _literal(settlement.get("buffer_hours")) + " hours"),
        ("Yield / party shares", _percent(settlement.get("yield_apr")) + " annual modeled APR; access " + _words(settlement.get("yield_access")) + "; " + _shared_yield(settlement))])
    _section(story, styles, "Evaluated scenario diagnostics", [
        ("Supply / bid ceiling", _rate(summary.get("supplier_rate")) + " / " + _rate(summary.get("purchase_ceiling")) + " - illustrative only"),
        ("Selling floor / target", _rate(summary.get("sell_floor")) + " / " + _rate(summary.get("target_ask")) + " - illustrative only"),
        ("Expected margin / profit", _percent(summary.get("expected_margin")) + " / " + _money(summary.get("expected_profit")) + "; denominator " + _words(summary.get("margin_basis"))),
        ("Opening / minimum cash", _money(treasury.get("opening_cash")) + " / " + _money(treasury.get("minimum_cash"))),
        ("Cash required", _money(summary.get("cash_required")) + " - modeled funding, not a transfer instruction"),
        ("NPV / annual IRR", _money(summary.get("npv")) + " / " + _percent(summary.get("irr")) + " - absent metrics remain unresolved")])
    story.append(Spacer(1, 10))
    story.append(_paragraph("Prepayment is cash paid once; invoice application is noncash; the remaining balance is separate. Expense recognition is not a second payment. No modeled rate, yield or return is promised.", styles["small"]))
    pricing = _group(terms, "pricing")
    story.append(_paragraph("NPV discount APR: " + _percent(pricing.get("discount_apr")) + ". Cash basis: " + _words(summary.get("npv_basis")) + ". IRR basis: " + _words(summary.get("irr_basis")) + ".", styles["small"]))
    model = (versions.get("evaluation.model") or versions.get("evaluation.demo") or versions.get("demo")) if isinstance(versions, Mapping) else None
    _section(story, styles, "Receipt and unresolved execution", [
        ("Evaluation created", created), ("Model / document", _literal(model) + " / " + VERSION),
        ("Canonical receipt SHA-256", identity[:32] + " " + identity[32:]),
        ("Law / authority / signatures", "UNRESOLVED / UNRESOLVED / NOT EXECUTED")])


def render_agreement_pdf(receipt):
    """Render three bounded unsigned pages from an integrity-checked saved demo."""
    identity, created, _, result, versions = _receipt(receipt)
    terms = result.get("agreement_terms")
    if (not isinstance(terms, Mapping) or terms.get("classification") != "synthetic"
            or terms.get("execution_enabled") is True):
        raise ValidationError("agreement: evaluated synthetic schedule required")
    for section in ("provider", "capacity", "pricing", "settlement", "treasury", "summary"):
        _group(terms, section)
    styles, story = _styles(), []
    _schedule(story, styles, terms)
    story.append(PageBreak())
    _operating_terms(story, styles, terms)
    story.append(PageBreak())
    _economic_supplement(story, styles, terms, identity, created, versions)
    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=letter, leftMargin=54, rightMargin=54,
        topMargin=66, bottomMargin=59, pageCompression=1, title="Compute Services - Nonbinding Demonstration",
        author="ComputeBasis", subject=MARKING, creator=VERSION)
    document.build(story, onFirstPage=lambda canvas, doc: _page(canvas, doc, identity),
        onLaterPages=lambda canvas, doc: _page(canvas, doc, identity), canvasmaker=_canvas)
    if document.page != 3:
        raise ValidationError("agreement: three-page layout budget exceeded")
    return output.getvalue()
