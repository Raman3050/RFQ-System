from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, EmailStr, PlainSerializer


def _to_utc(v: datetime) -> datetime:
    return v.astimezone(UTC)


# Inputs must carry a timezone; everything is normalised to UTC.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(_to_utc)]

# Outputs are always rendered as UTC ISO-8601 with a trailing Z.
UtcOut = Annotated[
    datetime,
    PlainSerializer(
        lambda v: v.astimezone(UTC).isoformat().replace("+00:00", "Z"), return_type=str
    ),
]

NormalizedEmail = Annotated[EmailStr, AfterValidator(lambda v: v.lower())]


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    size: int
    server_time: UtcOut
