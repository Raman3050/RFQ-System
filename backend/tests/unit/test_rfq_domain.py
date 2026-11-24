from datetime import UTC, date, datetime, timedelta

import pytest

from app.domain.rfq_rules import Schedule, validate_schedule
from app.domain.rfq_status import can_invite, effective_status, is_editable
from app.models.rfq import RfqStatus

NOW = datetime(2026, 11, 24, 17, 0, tzinfo=UTC)
H = timedelta(hours=1)


def schedule(start: timedelta = H, close: timedelta = 2 * H, forced: timedelta = 3 * H, **kw):
    return Schedule(
        bid_start_at=NOW + start,
        bid_close_at=NOW + close,
        forced_close_at=NOW + forced,
        pickup_date=kw.get("pickup", date(2026, 12, 1)),
    )


def codes(s: Schedule, **kw) -> set[str]:
    return {v.code for v in validate_schedule(s, now=NOW, **kw)}


class TestValidateSchedule:
    def test_valid(self) -> None:
        assert codes(schedule()) == set()

    def test_start_in_past(self) -> None:
        assert codes(schedule(start=-5 * timedelta(minutes=1))) == {"start_in_past"}

    def test_start_within_grace_is_ok(self) -> None:
        assert codes(schedule(start=-timedelta(seconds=30))) == set()

    def test_editing_may_keep_a_past_start(self) -> None:
        assert codes(schedule(start=-H), start_may_be_past=True) == set()

    @pytest.mark.parametrize("close", [H, H / 2])
    def test_close_must_be_after_start(self, close: timedelta) -> None:
        assert "close_before_start" in codes(schedule(close=close))

    @pytest.mark.parametrize("forced", [2 * H, H + H / 2])
    def test_forced_close_must_be_strictly_after_close(self, forced: timedelta) -> None:
        # Spec §7: equal is not allowed.
        assert "forced_close_not_after_close" in codes(schedule(forced=forced))

    def test_max_span(self) -> None:
        assert "auction_too_long" in codes(schedule(forced=timedelta(days=31)))

    def test_pickup_before_start(self) -> None:
        assert codes(schedule(pickup=date(2026, 11, 23))) == {"pickup_before_start"}

    def test_pickup_on_start_day_is_ok(self) -> None:
        assert codes(schedule(pickup=(NOW + H).date())) == set()

    def test_violation_shape_matches_request_validation_errors(self) -> None:
        [v] = validate_schedule(schedule(forced=2 * H), now=NOW)
        assert v.as_error() == {
            "loc": ["body", "forced_close_at"],
            "msg": "Forced close time must be later than the bid close time",
            "type": "forced_close_not_after_close",
        }


class TestEffectiveStatus:
    def status(self, now: datetime, stored: RfqStatus = RfqStatus.SCHEDULED, **kw) -> RfqStatus:
        return effective_status(
            stored,
            now=now,
            bid_start_at=kw.get("start", NOW),
            current_close_at=kw.get("close", NOW + H),
            forced_close_at=kw.get("forced", NOW + 2 * H),
        )

    def test_before_start(self) -> None:
        assert self.status(NOW - timedelta(seconds=1)) == RfqStatus.SCHEDULED

    def test_active_from_start_inclusive(self) -> None:
        assert self.status(NOW) == RfqStatus.ACTIVE

    def test_closed_at_close_exclusive(self) -> None:
        # Bidding window is [start, close): at the close instant the auction is over.
        assert self.status(NOW + H) == RfqStatus.CLOSED

    def test_force_closed_when_close_reached_the_cap(self) -> None:
        assert self.status(NOW + 2 * H, close=NOW + 2 * H) == RfqStatus.FORCE_CLOSED

    @pytest.mark.parametrize(
        "stored", [RfqStatus.CANCELLED, RfqStatus.CLOSED, RfqStatus.FORCE_CLOSED]
    )
    def test_terminal_stored_status_wins(self, stored: RfqStatus) -> None:
        assert self.status(NOW - H, stored=stored) == stored

    def test_stale_stored_active_after_close(self) -> None:
        # Worker hasn't run yet: readers still see the truth.
        assert self.status(NOW + 3 * H, stored=RfqStatus.ACTIVE) == RfqStatus.CLOSED


def test_permissions_by_status() -> None:
    assert is_editable(RfqStatus.SCHEDULED)
    assert not is_editable(RfqStatus.ACTIVE)
    assert can_invite(RfqStatus.SCHEDULED)
    assert can_invite(RfqStatus.ACTIVE)
    assert not can_invite(RfqStatus.CLOSED)
    assert not can_invite(RfqStatus.CANCELLED)
