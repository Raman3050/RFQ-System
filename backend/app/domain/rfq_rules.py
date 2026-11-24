"""RFQ schedule validation (spec §5 and §7). Pure functions, no I/O.

Returns field-level violations in the same shape as request validation errors, so the
frontend shows them next to the right input.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

# A little tolerance for clock skew and the time it takes to fill in the form.
START_GRACE = timedelta(minutes=1)
MAX_AUCTION_SPAN = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Violation:
    field: str
    code: str
    message: str

    def as_error(self) -> dict[str, object]:
        return {"loc": ["body", self.field], "msg": self.message, "type": self.code}


@dataclass(frozen=True, slots=True)
class Schedule:
    bid_start_at: datetime
    bid_close_at: datetime
    forced_close_at: datetime
    pickup_date: date


def validate_schedule(
    s: Schedule, *, now: datetime, start_may_be_past: bool = False
) -> list[Violation]:
    """`start_may_be_past` is True when editing an RFQ without changing its start time."""
    v: list[Violation] = []

    if not start_may_be_past and s.bid_start_at < now - START_GRACE:
        v.append(Violation("bid_start_at", "start_in_past", "Bid start time must be in the future"))

    if s.bid_close_at <= s.bid_start_at:
        v.append(
            Violation(
                "bid_close_at",
                "close_before_start",
                "Bid close time must be after the bid start time",
            )
        )

    # Spec §7: Forced Bid Close Time must always be greater than Bid Close Time.
    if s.forced_close_at <= s.bid_close_at:
        v.append(
            Violation(
                "forced_close_at",
                "forced_close_not_after_close",
                "Forced close time must be later than the bid close time",
            )
        )

    if s.forced_close_at - s.bid_start_at > MAX_AUCTION_SPAN:
        v.append(
            Violation(
                "forced_close_at",
                "auction_too_long",
                "An auction can run for at most 30 days from bid start to forced close",
            )
        )

    if s.pickup_date < s.bid_start_at.date():
        v.append(
            Violation(
                "pickup_date",
                "pickup_before_start",
                "Pickup / service date cannot be before bidding starts",
            )
        )

    return v
