"""사이트(도메인) 단위 수집 허용 상태 (DECISIONS D25).

- 새로 발견한 사이트는 검토 대기(pending_review)로 시작한다. 사람이 허용(allowed)해야 가져온다.
- 약관이 자동 수집을 금지하는 것으로 확인된 사이트는 처음부터 거부(denied)다 (DATA_POLICY 1–2).
- 사이트가 접근 거부·수집 금지·접근 제한 신호를 보내면 그 사이트만 차단(blocked)하고,
  자동으로 다시 시도하지 않는다. 다른 사이트의 수집은 계속된다.
"""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from narrative_radar.core.clock import Clock
from narrative_radar.db.models import SitePolicy
from narrative_radar.schemas.enums import SitePolicyStatus

# 약관이 자동 수집을 금지하는 사이트. 하위 도메인도 모두 포함한다 (DATA_POLICY 1–2).
DENYLIST: dict[str, str] = {
    "dcinside.com": "terms forbid automated collection (DATA_POLICY 1)",
    "naver.com": "no permitted automated access (DATA_POLICY 2)",
}

DEFAULT_DAILY_LIMIT = 20


def denylisted(site: str) -> str | None:
    for domain, reason in DENYLIST.items():
        if site == domain or site.endswith("." + domain):
            return reason
    return None


def ensure_policy(session: Session, clock: Clock, site: str) -> SitePolicy:
    """처음 보는 사이트면 검토 대기(또는 거부)로 등록한다."""
    policy = session.get(SitePolicy, site)
    if policy is not None:
        return policy
    now = clock.now()
    reason = denylisted(site)
    policy = SitePolicy(
        domain=site,
        status=SitePolicyStatus.DENIED if reason else SitePolicyStatus.PENDING_REVIEW,
        reason=reason or "discovered; waiting for review",
        decided_by="denylist" if reason else "discovery",
        daily_limit=DEFAULT_DAILY_LIMIT,
        consecutive_transient=0,
        created_at=now,
        updated_at=now,
    )
    session.add(policy)
    session.flush()
    return policy


def set_policy(
    session: Session,
    clock: Clock,
    site: str,
    status: SitePolicyStatus,
    reason: str,
    decided_by: str,
    daily_limit: int | None = None,
) -> SitePolicy:
    policy = ensure_policy(session, clock, site)
    if status == SitePolicyStatus.ALLOWED and (why := denylisted(site)):
        raise ValueError(f"{site} is on the denylist: {why}")
    now = clock.now()
    policy.status = status
    policy.reason = reason
    policy.decided_by = decided_by
    policy.updated_at = now
    if daily_limit is not None:
        policy.daily_limit = daily_limit
    if status == SitePolicyStatus.BLOCKED:
        policy.blocked_at = now
    elif status == SitePolicyStatus.ALLOWED:
        policy.consecutive_transient = 0
    return policy


def list_policies(session: Session, status: SitePolicyStatus | None = None) -> list[SitePolicy]:
    q = sa.select(SitePolicy).order_by(SitePolicy.status, SitePolicy.domain)
    if status is not None:
        q = q.where(SitePolicy.status == status)
    return list(session.scalars(q))
