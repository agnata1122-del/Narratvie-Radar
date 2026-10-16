"""차단 신호를 감지하면 수집을 멈춘다 (DATA_POLICY 5).

멈춘 뒤에는 이 프로세스 안에서 다시 요청하지 않는다. 해제는 사람이 원인을 확인한 뒤
`nr sources reset`으로 한다. 우회(프록시 회전, IP 변경, 캡차 풀이)는 하지 않는다.
"""

from dataclasses import dataclass, field

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


class CollectionBlocked(RuntimeError):
    """차단 신호 때문에 수집이 멈춘 상태에서 요청하려 할 때."""


@dataclass
class BlockGuard:
    max_consecutive_client_errors: int = 3
    tripped_reason: str | None = None
    _consecutive_client_errors: int = field(default=0, init=False)

    @property
    def tripped(self) -> bool:
        return self.tripped_reason is not None

    def check(self) -> None:
        if self.tripped_reason is not None:
            raise CollectionBlocked(self.tripped_reason)

    def trip(self, reason: str) -> None:
        if self.tripped_reason is None:
            self.tripped_reason = reason

    def observe(self, response: httpx.Response) -> None:
        """응답을 보고 차단 여부를 판단한다. 5xx는 서버 문제로 보고 차단으로 치지 않는다."""
        status = response.status_code
        if status in BLOCK_STATUS_CODES:
            self.trip(f"HTTP {status} from {response.request.url}")
            return

        location = str(response.url).lower()
        if any(m in location for m in LOGIN_PATH_MARKERS):
            self.trip(f"redirected to login page: {response.url}")
            return

        if status < 400 and _looks_like_challenge(response):
            self.trip(f"challenge page detected at {response.request.url}")
            return

        if status in GONE_STATUS_CODES:
            return  # 삭제된 글은 흔하다. 차단 신호로도, 정상 응답으로도 세지 않는다

        if 400 <= status < 500:
            self._consecutive_client_errors += 1
            if self._consecutive_client_errors >= self.max_consecutive_client_errors:
                self.trip(
                    f"{self._consecutive_client_errors} consecutive client errors "
                    f"(last HTTP {status} from {response.request.url})"
                )
        elif status < 400:
            self._consecutive_client_errors = 0


def _looks_like_challenge(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        return False
    # 정상 페이지 본문에 단어가 섞여 있을 수 있으므로 앞부분만 본다.
    head = response.text[:4000].lower()
    return any(marker in head for marker in BLOCK_BODY_MARKERS)
