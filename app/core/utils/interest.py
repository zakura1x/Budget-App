"""
interest - what a savings account earns while the money sits there (ACC-37).

Pure arithmetic: no session, no database, no clock. Two callers share it and
must never disagree - interest_service, which credits what has already been
earned, and projection_service, which grows a balance through months that have
not happened yet. Same discipline as recurring_service.occurrences(): one
formula, never re-derived.

The shape follows the Philippine digital banks the app is used with (SeaBank,
MariBank): an annual rate divided by 365, charged on YESTERDAY's closing
balance and credited at midnight, with a different rate on the part of a
balance above a threshold - e.g. 3.25% a year up to PHP 1,000,000 and 3.75% on
the excess. Interest is taxed at source (20% withholding), so what lands in
the account is the net.

Deliberately NOT quantised to two places: a day's interest on an ordinary
balance is a fraction of a centavo, and money.money() would round it away.
A day's net is carried at CARRY_PLACES until the total reaches one centavo,
which is what the banks themselves do - nothing under PHP 0.01 is credited,
and nothing under PHP 0.01 is lost.

Raises ValueError, like money.py: the service layer turns it into the API's
ValidationException.
"""

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from app.core.utils.money import CENTS, ZERO, money

YEAR_DAYS = 365  # how the banks divide the annual rate; 360 exists elsewhere
BASES: Tuple[int, ...] = (360, 365)
RATE_PLACES = Decimal("0.0001")  # 3.25%, and room for an odd promo rate
CARRY_PLACES = Decimal("0.00000001")  # the sub-centavo remainder, eight places
MAX_RATE = Decimal("100")
MAX_BANDS = 5

HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Band:
    """A rate and the balance it applies up to. `up_to` is None on the top band."""

    up_to: Optional[Decimal]
    rate: Decimal  # per cent a year


def parse_bands(raw: Any) -> Tuple[Band, ...]:
    """
    Read the stored (or submitted) band list, or raise ValueError.

    Ascending, at most MAX_BANDS, and only the last one open-ended: a list
    where a lower band has no ceiling would make every band above it dead
    weight that some later report has to remember to ignore.
    """
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise ValueError("an interest rate needs at least one band")
    if len(raw) > MAX_BANDS:
        raise ValueError(f"at most {MAX_BANDS} interest bands")

    bands: list[Band] = []
    previous: Optional[Decimal] = None
    for position, item in enumerate(raw, start=1):
        if isinstance(item, Band):
            ceiling, rate = item.up_to, item.rate
        elif isinstance(item, Mapping):
            ceiling, rate = item.get("up_to"), item.get("rate")
        else:
            raise ValueError(f"band {position}: not a rate")

        rate = _rate(rate, position)
        last = position == len(raw)
        if ceiling is None or (isinstance(ceiling, str) and not ceiling.strip()):
            if not last:
                raise ValueError(f"band {position}: only the top band may have no ceiling")
            bands.append(Band(None, rate))
            continue
        if last:
            raise ValueError("the top band applies to every balance above it - leave its ceiling empty")
        ceiling = money(ceiling)
        if ceiling <= ZERO:
            raise ValueError(f"band {position}: a ceiling is more than zero")
        if previous is not None and ceiling <= previous:
            raise ValueError("interest bands go from the lowest balance up")
        previous = ceiling
        bands.append(Band(ceiling, rate))
    return tuple(bands)


def dump_bands(bands: Iterable[Band]) -> list:
    """The bands as they are stored - strings, so nothing becomes a float (invariant 5)."""
    return [{"up_to": str(b.up_to) if b.up_to is not None else None, "rate": str(b.rate)} for b in bands]


def slices(balance: Decimal, bands: Sequence[Band]) -> Tuple[Tuple[Decimal, Band], ...]:
    """
    How much of `balance` sits in each band, lowest first. PHP 1,200,000 under
    (1,000,000 @ 3.25) + (open @ 3.75) is 1,000,000 at 3.25 and 200,000 at 3.75.
    """
    result: list[Tuple[Decimal, Band]] = []
    floor = ZERO
    for band in bands:
        if balance <= floor:
            break
        ceiling = balance if band.up_to is None else min(balance, band.up_to)
        if ceiling > floor:
            result.append((ceiling - floor, band))
        floor = ceiling
    return tuple(result)


def daily_gross(balance: Decimal, bands: Sequence[Band], *, basis: int = YEAR_DAYS) -> Decimal:
    """
    One day's interest before tax, unrounded. Nothing is earned on nothing, and
    nothing is earned on an overdrawn balance.
    """
    if balance <= ZERO or not bands:
        return ZERO
    divisor = Decimal(basis if basis in BASES else YEAR_DAYS)
    earned = ZERO
    for amount, band in slices(balance, bands):
        earned += amount * band.rate / HUNDRED / divisor
    return earned


def daily_net(
    balance: Decimal,
    bands: Sequence[Band],
    *,
    basis: int = YEAR_DAYS,
    tax_rate: Decimal = ZERO,
) -> Decimal:
    """
    One day's interest as it actually lands: gross less withholding tax (20% in
    the Philippines), unrounded and carried at CARRY_PLACES.
    """
    gross = daily_gross(balance, bands, basis=basis)
    if gross <= ZERO:
        return ZERO
    net = gross * (HUNDRED - tax_rate) / HUNDRED
    return net.quantize(CARRY_PLACES, rounding=ROUND_HALF_UP)


def credit(carry: Decimal) -> Tuple[Decimal, Decimal]:
    """
    (what is credited today, what is carried on). A bank pays out whole
    centavos only; the fraction left over waits for tomorrow rather than
    rounding up into money that was never earned.
    """
    if carry < CENTS:
        return ZERO, carry
    payable = carry.quantize(CENTS, rounding=ROUND_DOWN)
    return payable, (carry - payable).quantize(CARRY_PLACES, rounding=ROUND_HALF_UP)


def yearly_at(balance: Decimal, bands: Sequence[Band], *, basis: int = YEAR_DAYS,
              tax_rate: Decimal = ZERO) -> Decimal:
    """
    What this balance would earn in a year at today's rates, net of tax and
    without compounding - the "about PHP 1,295 a year" line on the account
    page. An estimate for a human, never a posted figure.
    """
    return (daily_net(balance, bands, basis=basis, tax_rate=tax_rate) * Decimal(basis)).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )


def _rate(value: Any, position: int) -> Decimal:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"band {position}: a rate is required")
    if isinstance(value, float):
        raise ValueError("a rate is Decimal, never float")
    try:
        rate = Decimal(str(value).strip().replace("%", ""))
    except Exception:  # noqa: BLE001 - any parse failure is the same answer
        raise ValueError(f"band {position}: not a rate") from None
    if not rate.is_finite() or rate < ZERO or rate > MAX_RATE:
        raise ValueError(f"band {position}: a rate is between 0 and {MAX_RATE}%")
    return rate.quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def rate_of(value: Any, what: str = "A rate") -> Decimal:
    """A single percentage - the withholding tax - checked the same way."""
    try:
        return _rate(value, 1)
    except ValueError:
        raise ValueError(f"{what} is between 0 and {MAX_RATE}%") from None
