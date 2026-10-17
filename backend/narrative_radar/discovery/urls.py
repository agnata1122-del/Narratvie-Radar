"""발견한 URL을 같은 글이면 같은 문자열이 되도록 정리한다 (DECISIONS D24).

- http(s)만 받는다. 사용자 정보(user:pass@)가 들어간 URL은 받지 않는다.
- 호스트는 소문자에 앞의 `www.`를 뗀다(같은 글이 두 주소로 잡히지 않게). 기본 포트·조각(#…)·
  추적용 매개변수(utm_* 등)는 지우고 나머지 매개변수는 정렬한다.
- 사이트 단위(차단기·허용 상태)는 그 호스트다. 하위 도메인은 따로 본다.
"""

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "igshid",
        "ref",
        "ref_src",
        "cmpid",
        "ocid",
        "smid",
        "taid",
        "spm",
    }
)
TRACKING_PREFIXES = ("utm_", "_hs", "itm_")
DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_url(url: str) -> str | None:
    """정리할 수 없는 URL(http(s)가 아님, 호스트 없음, 사용자 정보 포함)은 None."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".").removeprefix("www.")
    if scheme not in DEFAULT_PORTS or not host or parts.username or parts.password:
        return None
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    )
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query), ""))


def site_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").rstrip(".")
    return host.removeprefix("www.")


def url_key(canonical: str) -> str:
    """문서 external_id로 쓰는 짧은 키 (같은 글이면 같은 키)."""
    return "u:" + hashlib.sha1(canonical.encode()).hexdigest()[:32]
