"""Ranking and British Auction extension rules (spec §6), including the spec's own
worked examples. Pure functions: no DB, no clock."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.bidding import (
    AuctionRules,
    Quote,
    any_rank_changed,
    decide_extension,
    l1_changed,
    rank,
)
from app.models.rfq import TriggerType

A, B, C, D = (uuid.UUID(int=i) for i in range(1, 5))
SIX_PM = datetime(2026, 11, 24, 18, 0, tzinfo=UTC)
FORCED = SIX_PM + timedelta(minutes=30)
MIN = timedelta(minutes=1)


def q(supplier: uuid.UUID, total: str, at: datetime = SIX_PM - 30 * MIN) -> Quote:
    return Quote(supplier_id=supplier, bid_id=uuid.uuid4(), total=Decimal(total), created_at=at)


def rules(trigger: TriggerType, x: int = 10, y: int = 5) -> AuctionRules:
    return AuctionRules(trigger_window=x * MIN, extension=y * MIN, trigger_type=trigger)


# ---------------------------------------------------------------- ranking


class TestRank:
    def test_orders_by_total_ascending(self) -> None:
        ranked = rank([q(A, "300"), q(B, "100"), q(C, "200")])
        assert [r.supplier_id for r in ranked] == [B, C, A]

    def test_tie_goes_to_earlier_bid(self) -> None:
        early, late = SIX_PM - 20 * MIN, SIX_PM - 10 * MIN
        ranked = rank([q(A, "100", late), q(B, "100", early)])
        assert [r.supplier_id for r in ranked] == [B, A]

    def test_empty(self) -> None:
        assert rank([]) == []


class TestRankChanges:
    def test_no_change_when_order_is_identical(self) -> None:
        assert not any_rank_changed([A, B, C], [A, B, C])

    def test_swap_is_a_change(self) -> None:
        # Spec 6.3(b): "Supplier B underbids Supplier A ... rankings change".
        assert any_rank_changed([A, B], [B, A])

    def test_new_bidder_at_the_bottom_is_not_a_change(self) -> None:
        # Design decision D6: nobody who already had a rank moved.
        assert not any_rank_changed([A, B], [A, B, C])

    def test_new_bidder_above_others_is_a_change(self) -> None:
        assert any_rank_changed([A, B], [A, C, B])

    def test_first_ever_bid_is_not_a_change(self) -> None:
        assert not any_rank_changed([], [A])

    def test_l1_change(self) -> None:
        assert l1_changed([A, B], [B, A])
        assert not l1_changed([A, B], [A, C, B])  # L1 unchanged

    def test_first_bid_does_not_count_as_l1_change(self) -> None:
        # Design decision D7: a *change* of L1 needs a previous L1.
        assert not l1_changed([], [A])


# ---------------------------------------------------------------- extension decisions


def decide(
    trigger: TriggerType,
    now: datetime,
    before: list[uuid.UUID],
    after: list[uuid.UUID],
    *,
    close: datetime = SIX_PM,
    forced: datetime = FORCED,
    x: int = 10,
    y: int = 5,
):
    return decide_extension(
        rules(trigger, x, y),
        now=now,
        current_close=close,
        forced_close=forced,
        before=before,
        after=after,
    )


class TestSpecExamples:
    def test_6_1_and_6_2_window_and_extension(self) -> None:
        # Close 6:00 PM, X = 10 → monitored 5:50-6:00; Y = 5 → 6:00 → 6:05.
        d = decide(TriggerType.BID_RECEIVED, SIX_PM - 5 * MIN, [A], [A])
        assert d.extend
        assert d.new_close == SIX_PM + 5 * MIN

    def test_6_3_a_bid_at_5_55_extends(self) -> None:
        d = decide(TriggerType.BID_RECEIVED, SIX_PM - 5 * MIN, [A, B], [A, B])
        assert d.extend
        assert d.reason == "Bid received in the last 10 minutes"

    def test_6_3_b_underbid_at_5_58_extends(self) -> None:
        d = decide(TriggerType.ANY_RANK_CHANGE, SIX_PM - 2 * MIN, [A, B], [B, A])
        assert d.extend
        assert d.reason == "Supplier ranking changed in the last 10 minutes"

    def test_6_3_c_new_l1_at_5_59_extends(self) -> None:
        d = decide(TriggerType.L1_RANK_CHANGE, SIX_PM - MIN, [A, B, C], [C, A, B])
        assert d.extend
        assert d.reason == "New lowest bidder (L1) in the last 10 minutes"


class TestWindow:
    def test_window_start_is_inclusive(self) -> None:
        assert decide(TriggerType.BID_RECEIVED, SIX_PM - 10 * MIN, [], [A]).extend

    def test_before_window_does_not_extend(self) -> None:
        d = decide(TriggerType.BID_RECEIVED, SIX_PM - 10 * MIN - timedelta(seconds=1), [], [A])
        assert not d.extend
        assert d.reason == "outside trigger window"

    def test_window_slides_with_extensions(self) -> None:
        # After one extension close is 6:05, so 5:56 is inside the window [5:55, 6:05).
        d = decide(TriggerType.BID_RECEIVED, SIX_PM - 4 * MIN, [A], [A], close=SIX_PM + 5 * MIN)
        assert d.extend
        assert d.new_close == SIX_PM + 10 * MIN


class TestTriggerTypesDoNotOverfire:
    def test_rank_trigger_ignores_bid_that_keeps_order(self) -> None:
        d = decide(TriggerType.ANY_RANK_CHANGE, SIX_PM - MIN, [A, B], [A, B])
        assert not d.extend
        assert d.reason == "no ranking change"

    def test_l1_trigger_ignores_change_below_l1(self) -> None:
        d = decide(TriggerType.L1_RANK_CHANGE, SIX_PM - MIN, [A, B, C], [A, C, B])
        assert not d.extend
        assert d.reason == "L1 unchanged"


class TestForcedClose:
    def test_extension_is_capped_at_forced_close(self) -> None:
        # Spec rule: never extend beyond the forced close time.
        d = decide(TriggerType.BID_RECEIVED, SIX_PM - MIN, [A], [A], forced=SIX_PM + 2 * MIN)
        assert d.extend
        assert d.new_close == SIX_PM + 2 * MIN
        assert d.capped

    def test_no_extension_once_at_forced_close(self) -> None:
        d = decide(
            TriggerType.BID_RECEIVED,
            SIX_PM - MIN,
            [A],
            [A],
            close=SIX_PM,
            forced=SIX_PM,
        )
        assert not d.extend
        assert d.reason == "already at forced close"

    @pytest.mark.parametrize("y", [1, 5, 29, 30, 31, 600])
    def test_new_close_never_exceeds_forced(self, y: int) -> None:
        d = decide(TriggerType.BID_RECEIVED, SIX_PM - MIN, [A], [A], y=y)
        assert d.new_close is not None
        assert d.new_close <= FORCED
        assert d.capped == (SIX_PM + y * MIN >= FORCED)
