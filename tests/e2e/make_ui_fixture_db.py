"""화면 확인용 픽스처 DB를 만든다 (UI 렌더링·e2e 전용).

여기 들어가는 글과 분류 결과는 **직접 만든 형식 확인용 예시**다. 실제 커뮤니티 글이 아니고,
서사 품질 평가나 데모에 쓰지 않는다 (DECISIONS D0·D13). 글 본문은 모두 "UI fixture"로 시작하고
링크는 example.invalid 로 둔다. 만든 DB는 data/ 처럼 커밋하지 않는 곳에 둔다.

    uv run python tests/e2e/make_ui_fixture_db.py /tmp/ui-fixture.db
    NR_DB_PATH=/tmp/ui-fixture.db uv run nr serve
"""

import hashlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))

from graphkit import HBM, NV, POWER, SKH, GraphKit  # noqa: E402

from narrative_radar.collectors.prices import MARKETS, day_closes_at  # noqa: E402
from narrative_radar.core.clock import FixedClock  # noqa: E402
from narrative_radar.core.ids import new_id  # noqa: E402
from narrative_radar.db.migrate import upgrade_to_head  # noqa: E402
from narrative_radar.db.models import Document, PriceBar  # noqa: E402
from narrative_radar.db.session import make_engine, make_session_factory  # noqa: E402
from narrative_radar.ingest.health import record_health  # noqa: E402
from narrative_radar.ingest.runs import start_run  # noqa: E402
from narrative_radar.schemas.document import DocumentIn  # noqa: E402
from narrative_radar.schemas.enums import RunKind, SourceHealthStatus  # noqa: E402
from narrative_radar.wiki.build import refresh_wiki  # noqa: E402

TSMC = ("TSMC", "organization", "TW:2330")
AMD = ("AMD", "organization", "US:AMD")
COWOS = ("CoWoS", "technology", "TECH:cowos")
SAMSUNG = ("Samsung Electronics", "organization", "KR:005930")

WORDS = [
    "amber",
    "basin",
    "cobalt",
    "delta",
    "ember",
    "fjord",
    "granite",
    "harbor",
    "iris",
    "jasper",
    "kelp",
    "lumen",
    "maple",
    "nectar",
    "onyx",
    "prism",
    "quartz",
    "raven",
    "sierra",
    "tundra",
    "umber",
    "violet",
    "willow",
    "xenon",
    "yarrow",
    "zephyr",
]


def words(n: int, k: int = 14) -> str:
    """글마다 다른 단어 조합. 복제 판정(SimHash)에 서로 다른 글로 잡히게 한다."""
    return " ".join(WORDS[(n * 7 + i * (n % 5 + 1)) % len(WORDS)] for i in range(k))


class FixtureKit(GraphKit):
    def doc(self, text, author="a", mode="live", published=None):
        self.n += 1
        ext = f"ui-fixture-{self.n}"
        published = published or self.clock.now()
        r = self.store.save(
            DocumentIn(
                source_adapter_id="hackernews",
                external_id=ext,
                source_url=f"https://example.invalid/fixture/{self.n}",
                title="",
                body_text=f"UI fixture {self.n}: {text} {words(self.n)}",
                author_hash=hashlib.sha256(author.encode()).hexdigest(),
                published_at=published,
                observed_at=max(published, self.clock.now()),
                content_access_status="permitted",
                ingest_mode=mode,
            )
        )
        return self.session.get(Document, r.document_id)


def claim(s, p, o, **extra):
    return (s[0], p, o[0], {"excerpt": f"fixture claim: {s[0]} {p} {o[0]}", **extra})


# 형식 확인용 예시 가격 (실제 시세 아님, D27): 종목마다 정해진 기울기와 흔들림으로 만든 값
FIXTURE_PRICES = {
    "US:NVDA": (100.0, 0.012),
    "US:AMD": (80.0, -0.006),
    "KR:000660": (200000.0, 0.009),
    "KR:005930": (60000.0, -0.004),
}


def add_price_bars(session, clock) -> None:
    run_id = start_run(session, clock, RunKind.COLLECT).run_id
    now = clock.now()
    for key, (base, slope) in FIXTURE_PRICES.items():
        market = key.split(":")[0]
        for i in range(21, 0, -1):
            day = (now - timedelta(days=i)).astimezone(MARKETS[market].tz).date()
            if day.weekday() >= 5:
                continue
            step = 21 - i
            close = base * (1 + slope * step + 0.008 * ((step * 7) % 5 - 2))
            session.add(
                PriceBar(
                    bar_id=new_id("pbr", now),
                    source_adapter_id="toss_prices",
                    canonical_key=key,
                    interval="1d",
                    bar_date=day,
                    open=close,
                    high=close * 1.01,
                    low=close * 0.99,
                    close=close,
                    volume=None,
                    currency="KRW" if market == "KR" else None,
                    closes_at=day_closes_at(market, day),
                    fetched_at=now,
                    run_id=run_id,
                )
            )


def main(out: Path) -> None:
    if out.exists():
        out.unlink()
    url = f"sqlite:///{out}"
    upgrade_to_head(url)
    engine = make_engine(url)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    # 마지막 변화가 최근 24시간 안에 들어오도록 시작 시각을 잡는다
    clock = FixedClock(now - timedelta(hours=195))
    hbm_limits = {"narrative_proposition": "HBM supply limits NVIDIA shipments"}

    with make_session_factory(engine)() as session:
        g = FixtureKit(session, clock)

        def pair(a, b, pred, authors=("a", "b"), **extra):
            for author in authors:
                g.post(f"{a[0]} {b[0]}", [a, b], [claim(a, pred, b, **extra)], author=author)

        def tick(hours: int) -> None:
            g.build()
            refresh_wiki(session, clock, start_run(session, clock, RunKind.WIKI).run_id, g.profile)
            session.commit()
            clock.advance(timedelta(hours=hours))

        # 하루 단위로 관계가 생기고, 확정되고, 논쟁이 붙는 흐름 (형식 확인용)
        pair(HBM, NV, "AFFECTS", narrative_role="supports", **hbm_limits)
        tick(20)
        pair(SKH, HBM, "SUPPLIES_TO", authors=("c", "d"))
        tick(26)
        pair(POWER, NV, "AFFECTS", authors=("e", "f"))
        tick(22)
        g.post("TSMC NVIDIA", [TSMC, NV], [claim(TSMC, "SUPPLIES_TO", NV)], author="g")
        record_health(
            session,
            clock,
            "hackernews",
            clock.now() - timedelta(hours=6),
            clock.now() - timedelta(hours=1),
            SourceHealthStatus.DOWN,
            note="fixture gap",
        )
        tick(25)
        pair(AMD, NV, "COMPETES_WITH", authors=("h", "i"))
        g.post("HBM NVIDIA", [HBM, NV], [claim(HBM, "AFFECTS", NV)], author="j")
        tick(24)
        for author in ("k", "l", "m"):
            g.post(
                "HBM NVIDIA",
                [HBM, NV],
                [claim(HBM, "AFFECTS", NV, narrative_role="contradicts", **hbm_limits)],
                author=author,
            )
        tick(23)
        pair(COWOS, TSMC, "PART_OF", authors=("n", "o"))
        g.post("TSMC NVIDIA", [TSMC, NV], [claim(TSMC, "SUPPLIES_TO", NV)], author="p")
        g.post("Samsung HBM", [SAMSUNG, HBM], [claim(SAMSUNG, "SUPPLIES_TO", HBM)], author="q")
        tick(25)
        for author in "rstuvw":
            g.post("power NVIDIA", [POWER, NV], [], author=author)
        tick(24)
        pair(
            POWER,
            NV,
            "AFFECTS",
            authors=("x", "y"),
            narrative_role="supports",
            narrative_proposition="Data center power caps AI build-out",
        )
        tick(1)
        add_price_bars(session, clock)
        session.commit()
    engine.dispose()
    print(f"UI fixture DB written to {out} (format-only test data, not real posts)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: make_ui_fixture_db.py OUT.db")
    main(Path(sys.argv[1]))
