"""수집 중 문제가 생기면 그 즉시 멈춘다 (DATA_POLICY 5).

- 차단 신호(401/403/429, 캡차·차단 안내 페이지, 로그인 리다이렉트) → BLOCKED
- 그 밖의 문제(다른 4xx, 5xx, 타임아웃·연결 오류, robots.txt 확인 불가, 파싱 실패) → ERROR
- 예외: 삭제된 글(404/410)은 흔하므로 문제로 보지 않는다.

한 번 멈추면 이 프로세스 안에서는 다시 요청하지 않는다. 재개는 사람이 원인을 확인한 뒤
`nr sources reset`으로 한다. 차단을 피하려는 우회(IP·VPN 서버 변경, 프록시 회전, 캡차 풀이)는
하지 않는다.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import httpx

BLOCK_STATUS_CODES = frozenset({401, 403, 429})
GONE_STATUS_CODES = frozenset({404, 410})

# 본문에 이런 표지가 있으면 사람 확인 페이지로 본다.
BLOCK_BODY_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "보안문자",
    "자동입력 방지",
    "자동 입력 방지",
    "비정상적인 접근",
    "접근이 차단",
)

LOGIN_PATH_MARKERS = ("/login", "/signin", "nid.naver.com", "sign.dcinside.com")


class TripKind(StrEnum):
    BLOCKED = "blocked"  # 사이트가 차단 신호를 보냄
    ERROR = "error"  # 그 밖의 문제


class CollectionBlocked(RuntimeError):
    """수집이 멈춘 상태에서 요청하려 할 때."""


@dataclass
class BlockGuard:
    # 멈추는 순간 호출된다. 수집 실행기가 여기서 DB의 소스 상태를 바로 바꾼다.
    on_trip: Callable[[TripKind, str], None] | None = None
    tripped_kind: TripKind | None = None
    tripped_reason: str | None = None

    @property
    def tripped(self) -> bool:
        return self.tripped_reason is not None

    def check(self) -> None:
        if self.tripped_reason is not None:
            raise CollectionBlocked(f"{self.tripped_kind}: {self.tripped_reason}")

    def trip(self, kind: TripKind, reason: str) -> None:
        if self.tripped_reason is not None:
            return
        self.tripped_kind = kind
        self.tripped_reason = reason
        if self.on_trip is not None:
            self.on_trip(kind, reason)

    def observe(self, response: httpx.Response) -> None:
        status = response.status_code
        url = response.request.url
        if status in BLOCK_STATUS_CODES:
            self.trip(TripKind.BLOCKED, f"HTTP {status} from {url}")
        elif any(m in str(response.url).lower() for m in LOGIN_PATH_MARKERS):
            self.trip(TripKind.BLOCKED, f"redirected to login page: {response.url}")
        elif status < 400 and _looks_like_challenge(response):
            self.trip(TripKind.BLOCKED, f"challenge page detected at {url}")
        elif status in GONE_STATUS_CODES:
            return
        elif status >= 400:
            self.trip(TripKind.ERROR, f"HTTP {status} from {url}")

    def observe_exception(self, url: str, exc: Exception) -> None:
        self.trip(TripKind.ERROR, f"{type(exc).__name__} for {url}: {exc}")


def _looks_like_challenge(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        return False
    # 정상 페이지 본문에 단어가 섞여 있을 수 있으므로 앞부분만 본다.
    head = response.text[:4000].lower()
    return any(marker in head for marker in BLOCK_BODY_MARKERS)
