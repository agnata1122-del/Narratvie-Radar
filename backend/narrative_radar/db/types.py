from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """시간대가 있는 datetime만 받아 UTC ISO 문자열로 저장하고, UTC aware로 돌려준다.

    SQLite는 시간대를 보존하지 않으므로 직접 변환한다. 시간대가 없는 값은 거부한다:
    출처 시각을 추측해 붙이면 available_at 기반 복원이 틀어지기 때문이다.
    """

    impl = sa.String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: sa.Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"expected datetime, got {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError(f"naive datetime is not allowed: {value!r}")
        # 고정 길이로 저장해서 문자열 비교가 시간 비교와 같아지게 한다.
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def process_result_value(self, value: str | None, dialect: sa.Dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def str_enum(enum_cls: type[StrEnum]) -> sa.Enum:
    """열거형 값을 문자열로 저장한다. 잘못된 값은 쓰기 전에 거부된다."""
    return sa.Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )
