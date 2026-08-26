"""Server-authoritative money math. Decimal only — floats never touch currency.

Line calculation (shared by quotations, orders, invoices):
    gross    = quantity * unit_price
    discount = gross * discount_percent / 100
    net      = gross - discount
    tax      = net * tax_rate / 100
    total    = net + tax
Each derived value is rounded half-up to 2 decimal places at the line level;
header totals are sums of the rounded line values, so documents always add up.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import NamedTuple

TWO_PLACES = Decimal("0.01")


def money(value: Decimal | str | int) -> Decimal:
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class LineAmounts(NamedTuple):
    gross: Decimal
    discount: Decimal
    net: Decimal
    tax: Decimal
    total: Decimal


def calculate_line(
    quantity: Decimal,
    unit_price: Decimal,
    discount_percent: Decimal = Decimal("0"),
    tax_rate: Decimal = Decimal("0"),
) -> LineAmounts:
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if unit_price < 0:
        raise ValueError("unit_price cannot be negative")
    if not (Decimal("0") <= discount_percent <= Decimal("100")):
        raise ValueError("discount_percent out of range")

    gross = money(Decimal(quantity) * Decimal(unit_price))
    discount = money(gross * Decimal(discount_percent) / Decimal("100"))
    net = money(gross - discount)
    tax = money(net * Decimal(tax_rate) / Decimal("100"))
    total = money(net + tax)
    return LineAmounts(gross, discount, net, tax, total)


class DocumentTotals(NamedTuple):
    subtotal: Decimal        # sum of gross
    discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal


def sum_lines(lines: list[LineAmounts]) -> DocumentTotals:
    subtotal = money(sum((line.gross for line in lines), Decimal("0")))
    discount_total = money(sum((line.discount for line in lines), Decimal("0")))
    tax_total = money(sum((line.tax for line in lines), Decimal("0")))
    grand_total = money(sum((line.total for line in lines), Decimal("0")))
    return DocumentTotals(subtotal, discount_total, tax_total, grand_total)
