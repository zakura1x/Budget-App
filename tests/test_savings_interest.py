"""
ACC-37 - daily savings interest, the way SeaBank and MariBank pay it.

What must hold: a day's interest is earned on YESTERDAY's closing balance and
compounds; today is never credited; tax comes off before the money lands;
anything under a centavo is carried, never rounded away or lost; a catch-up run
twice changes nothing; an entry the user deletes is not written back; and the
months ahead use the same arithmetic as the days behind.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.exceptions import ValidationException
from app.core.utils.interest import credit, daily_gross, daily_net, parse_bands, yearly_at
from app.services import (
    account_service,
    category_service,
    interest_service,
    projection_service,
    transaction_service,
)

TODAY = date(2026, 9, 16)
STARTED = date(2026, 9, 11)
BANDS = [{"up_to": "1000000.00", "rate": "3.25"}, {"up_to": None, "rate": "3.75"}]
TAX = "20"


def setup(session, owner, *, opening="39850.17", started=STARTED, bands=None):
    """A savings account paying the MariBank rate, and the category interest lands in."""
    earnings = category_service.create_category(session, owner, {"name": "Interest", "kind": "income"})
    account = account_service.create_account(session, owner, {
        "name": "Seabank", "type": "savings", "opening_balance": opening,
        "interest": {"bands": bands or BANDS, "tax_rate": TAX, "category_id": earnings.id,
                     "started": started.isoformat()},
    })
    return account, earnings


def entries(session, owner, account_id):
    """Every interest credit on the account, oldest first."""
    return sorted(
        (v for v in transaction_service.views(session, owner) if v.interest_on is not None
         and v.account_id == account_id),
        key=lambda v: v.interest_on,
    )


def balance(session, owner, account_id, today=TODAY):
    return account_service.get_account(
        session, owner, account_id, postings=transaction_service.postings(session, owner), today=today
    ).balance


# ------------------------------------------------------------------ the arithmetic


def test_bands_split_at_the_threshold():
    """PHP 1.2M is a million at 3.25% and the rest at 3.75% - 40,000 a year gross."""
    bands = parse_bands(BANDS)
    assert (daily_gross(Decimal("1200000.00"), bands) * 365).quantize(Decimal("0.01")) == Decimal("40000.00")
    # Exactly at the threshold, the top band has nothing in it.
    assert (daily_gross(Decimal("1000000.00"), bands) * 365).quantize(Decimal("0.01")) == Decimal("32500.00")


def test_tax_comes_off_before_the_money_lands():
    bands = parse_bands(BANDS)
    gross = daily_gross(Decimal("39850.17"), bands)
    net = daily_net(Decimal("39850.17"), bands, tax_rate=Decimal(TAX))
    assert gross.quantize(Decimal("0.01")) == Decimal("3.55")
    assert net.quantize(Decimal("0.01")) == Decimal("2.84")
    assert yearly_at(Decimal("39850.17"), bands, tax_rate=Decimal(TAX)) == (net * 365).quantize(Decimal("0.01"))


def test_nothing_is_earned_on_nothing_or_on_an_overdraft():
    bands = parse_bands(BANDS)
    assert daily_net(Decimal("0.00"), bands, tax_rate=Decimal(TAX)) == Decimal("0.00")
    assert daily_net(Decimal("-500.00"), bands, tax_rate=Decimal(TAX)) == Decimal("0.00")


def test_a_fraction_of_a_centavo_is_carried_not_lost():
    """PHP 100 earns 0.0071 a day: a centavo lands every other day and the rest waits."""
    bands = parse_bands(BANDS)
    carry, paid = Decimal("0"), Decimal("0")
    for _ in range(10):
        carry += daily_net(Decimal("100.00"), bands, tax_rate=Decimal(TAX))
        payable, carry = credit(carry)
        paid += payable
    assert paid == Decimal("0.07")
    assert paid + carry == (daily_net(Decimal("100.00"), bands, tax_rate=Decimal(TAX)) * 10)


def test_a_band_list_has_to_make_sense():
    with pytest.raises(ValueError):
        parse_bands([{"up_to": None, "rate": "3.25"}, {"up_to": "1000000.00", "rate": "3.75"}])
    with pytest.raises(ValueError):
        parse_bands([{"up_to": "1000000.00", "rate": "3.25"}])  # the top band needs no ceiling
    with pytest.raises(ValueError):
        parse_bands([{"up_to": "2000.00", "rate": "3.25"}, {"up_to": "1000.00", "rate": "3.75"},
                     {"up_to": None, "rate": "4.00"}])
    with pytest.raises(ValueError):
        parse_bands([{"up_to": None, "rate": 3.25}])  # a float never becomes a rate


# ------------------------------------------------------------------ the catch-up


def test_one_entry_a_day_up_to_yesterday(session, owner):
    account, earnings = setup(session, owner)
    result = interest_service.accrue(session, owner, today=TODAY)

    posted = entries(session, owner, account.id)
    assert [v.interest_on for v in posted] == [STARTED + timedelta(days=n) for n in range(5)]
    assert result.posted == 5 and result.accounts == 1 and result.through == TODAY - timedelta(days=1)
    # Today is never credited: its closing balance is not closed yet.
    assert TODAY not in {v.interest_on for v in posted}
    # Net of tax, on the opening balance, and filed where the user asked.
    assert posted[0].amount == Decimal("2.83")
    assert [s.category_id for s in posted[0].splits] == [earnings.id]
    assert posted[0].type == "income"


def test_the_credit_compounds(session, owner):
    account, _ = setup(session, owner)
    interest_service.accrue(session, owner, today=TODAY)
    posted = entries(session, owner, account.id)
    # Each day earns on the day before it, interest included, so the amounts never fall.
    assert all(b.amount >= a.amount for a, b in zip(posted, posted[1:]))
    assert balance(session, owner, account.id) == Decimal("39850.17") + sum(v.amount for v in posted)


def test_running_it_twice_changes_nothing(session, owner):
    account, _ = setup(session, owner)
    first = interest_service.accrue(session, owner, today=TODAY)
    again = interest_service.accrue(session, owner, today=TODAY)
    assert (again.posted, again.credited) == (0, Decimal("0.00"))
    assert len(entries(session, owner, account.id)) == first.posted


def test_a_deleted_entry_is_not_written_back(session, owner):
    account, _ = setup(session, owner)
    interest_service.accrue(session, owner, today=TODAY)
    posted = entries(session, owner, account.id)
    transaction_service.delete_transaction(session, owner, posted[0].id)

    interest_service.accrue(session, owner, today=TODAY)
    assert len(entries(session, owner, account.id)) == len(posted) - 1


def test_the_carry_survives_between_runs(session, owner):
    """A balance too small to earn a centavo a day still earns - a day later."""
    account, _ = setup(session, owner, opening="100.00", started=TODAY - timedelta(days=1))
    interest_service.accrue(session, owner, today=TODAY)
    assert entries(session, owner, account.id) == []

    later = interest_service.accrue(session, owner, today=TODAY + timedelta(days=1))
    assert later.posted == 1
    assert entries(session, owner, account.id)[0].amount == Decimal("0.01")


def test_a_later_run_picks_up_where_it_left_off(session, owner):
    account, _ = setup(session, owner)
    interest_service.accrue(session, owner, today=TODAY)
    interest_service.accrue(session, owner, today=TODAY + timedelta(days=3))
    assert len(entries(session, owner, account.id)) == 8


def test_money_paid_in_earns_from_the_next_day(session, owner):
    account, _ = setup(session, owner, opening="100000.00", started=TODAY - timedelta(days=3))
    transaction_service.create_transaction(session, owner, {
        "type": "income", "amount": "900000.00", "account_id": account.id,
        "category_id": category_service.create_category(session, owner, {"name": "Pay", "kind": "income"}).id,
        "txn_date": (TODAY - timedelta(days=2)).isoformat(),
    })
    interest_service.accrue(session, owner, today=TODAY)
    posted = entries(session, owner, account.id)
    # The day the money arrived still earns on the old balance - it is yesterday's
    # CLOSING balance that counts - and the day after earns on the new one.
    assert [v.amount for v in posted[:2]] == [Decimal("7.12"), Decimal("7.12")]
    assert posted[2].amount == Decimal("71.24")


def test_an_archived_category_stops_the_account_and_says_so(session, owner):
    account, earnings = setup(session, owner)
    category_service.update_category(session, owner, earnings.id,
                                     {"name": "Interest", "kind": "income", "archived": True})
    result = interest_service.accrue(session, owner, today=TODAY)
    assert result.posted == 0 and result.needs_attention == (account.id,)
    assert entries(session, owner, account.id) == []


# ------------------------------------------------------------------ the account


def test_the_account_shows_what_a_day_and_a_year_are_worth(session, owner):
    account, _ = setup(session, owner)
    view = account_service.get_account(session, owner, account.id,
                                       postings=transaction_service.postings(session, owner), today=TODAY)
    assert view.interest is not None
    assert view.interest.per_day == Decimal("2.84")  # net, at today's balance
    assert view.interest.per_year == Decimal("1036.10")
    assert view.interest.started == STARTED


def test_a_card_never_earns_interest(session, owner):
    earnings = category_service.create_category(session, owner, {"name": "Interest", "kind": "income"})
    card = account_service.create_account(session, owner, {
        "name": "Card", "type": "credit", "statement_closing_day": 15, "payment_due_day": 5,
        "interest": {"bands": BANDS, "tax_rate": TAX, "category_id": earnings.id},
    })
    assert card.interest is None
    assert interest_service.accrue(session, owner, today=TODAY).posted == 0


def test_changing_the_rate_leaves_what_was_credited_alone(session, owner):
    account, earnings = setup(session, owner)
    interest_service.accrue(session, owner, today=TODAY)
    before = [(v.interest_on, v.amount) for v in entries(session, owner, account.id)]

    account_service.update_account(session, owner, account.id, {
        "name": "Seabank", "type": "savings",
        "interest": {"bands": [{"up_to": None, "rate": "6.00"}], "tax_rate": TAX, "category_id": earnings.id,
                     "started": "2026-01-01"},
    }, postings=transaction_service.postings(session, owner), today=TODAY)

    interest_service.accrue(session, owner, today=TODAY)
    assert [(v.interest_on, v.amount) for v in entries(session, owner, account.id)] == before


def test_turning_interest_off_keeps_the_history_and_stops_the_credits(session, owner):
    account, _ = setup(session, owner)
    interest_service.accrue(session, owner, today=TODAY)
    posted = len(entries(session, owner, account.id))

    account_service.update_account(session, owner, account.id, {"name": "Seabank", "type": "savings",
                                                                "interest": None},
                                   postings=transaction_service.postings(session, owner), today=TODAY)
    interest_service.accrue(session, owner, today=TODAY + timedelta(days=5))
    assert len(entries(session, owner, account.id)) == posted


def test_an_edit_that_says_nothing_about_interest_keeps_it(session, owner):
    account, _ = setup(session, owner)
    account_service.update_account(session, owner, account.id, {"name": "SeaBank", "type": "savings"},
                                   postings=transaction_service.postings(session, owner), today=TODAY)
    assert interest_service.accrue(session, owner, today=TODAY).posted == 5


def test_a_start_date_beyond_the_backfill_is_refused(session, owner):
    earnings = category_service.create_category(session, owner, {"name": "Interest", "kind": "income"})
    with pytest.raises(ValidationException):
        account_service.create_account(session, owner, {
            "name": "Old", "type": "savings",
            "interest": {"bands": BANDS, "tax_rate": TAX, "category_id": earnings.id, "started": "2020-01-01"},
        })


def test_interest_needs_somewhere_to_land(session, owner):
    with pytest.raises(ValidationException):
        account_service.create_account(session, owner, {
            "name": "Nowhere", "type": "savings", "interest": {"bands": BANDS, "tax_rate": TAX},
        })


# ------------------------------------------------------------------ months ahead


def test_the_months_ahead_count_the_interest(session, owner):
    account, _ = setup(session, owner)
    projection = projection_service.project(session, owner, today=TODAY, months=3)
    items = [i for month in projection.months for i in month.items if i.kind == "interest"]
    assert len(items) == 3
    assert all(i.account_id == account.id and i.type == "income" for i in items)
    # A full month at this balance is about 30 days of what a day earns.
    full = next(i for i in projection.months[1].items if i.kind == "interest")
    assert Decimal("80.00") < full.amount < Decimal("90.00")
    assert projection.months[1].income >= full.amount


def test_an_account_out_of_cash_on_hand_is_out_of_the_projection(session, owner):
    account, _ = setup(session, owner)
    account_service.update_account(session, owner, account.id,
                                   {"name": "Seabank", "type": "savings", "counts_in_cash_on_hand": False},
                                   postings=transaction_service.postings(session, owner), today=TODAY)
    projection = projection_service.project(session, owner, today=TODAY, months=3)
    assert [i for month in projection.months for i in month.items if i.kind == "interest"] == []


# ------------------------------------------------------------------ over the wire


def test_the_api_sets_reads_and_accrues(api):
    api.register()
    earnings = api.post("/categories", {"name": "Interest", "kind": "income"}).json()
    created = api.post("/accounts", {"name": "Seabank", "type": "savings", "opening_balance": "39850.17"}).json()

    saved = api.patch(f"/accounts/{created['id']}", {
        "name": "Seabank", "type": "savings",
        "interest": {"bands": [{"up_to": "1000000.00", "rate": "3.25"}, {"up_to": None, "rate": "3.75"}],
                     "tax_rate": "20", "category_id": earnings["id"]},
    })
    assert saved.status_code == 200, saved.text
    interest = saved.json()["interest"]
    assert interest["per_day"] == "2.84" and interest["tax_rate"] == "20.0000"
    assert [b["rate"] for b in interest["bands"]] == ["3.2500", "3.7500"]

    # Interest starts today by default, so there is nothing to credit yet.
    first = api.post("/accounts/interest/accrue")
    assert first.status_code == 200, first.text
    assert first.json()["posted"] == 0
    # ...and "interest" is read as the route it is, never as an account id.
    assert api.get(f"/accounts/{created['id']}").json()["interest"]["category_id"] == earnings["id"]


def test_the_api_refuses_a_rate_as_a_number(api):
    api.register()
    earnings = api.post("/categories", {"name": "Interest", "kind": "income"}).json()
    response = api.post("/accounts", {
        "name": "Seabank", "type": "savings",
        "interest": {"bands": [{"up_to": None, "rate": 3.25}], "category_id": earnings["id"]},
    })
    assert response.status_code == 422
