# Narrative Radar

**From fragmented conversations to evolving intelligence.**

관심사 하나(첫 대상: NVIDIA)를 등록하면, 선택한 커뮤니티에서 관측된 주장과 이슈를 지식 그래프로 묶고, 그 관계가 시간에 따라 어떻게 달라지는지를 근거와 함께 보여주는 웹앱입니다.

미래를 예측하는 도구가 아니라, 지금 일어나고 있지만 놓치기 쉬운 변화를 발견하는 도구입니다. 이 앱이 보여주는 내용은 투자 조언이 아닙니다.

> **현재 상태: 개발 초기 (v0.2).** 수집기(Bluesky, HN)까지 만들었고, 실제 수집 확인(M2)을 앞두고 있습니다. 라이브 수집은 기본값이 꺼짐입니다. 진행 상황은 [docs/ROADMAP.md](docs/ROADMAP.md)를 보세요.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 제품 요구사항 원문 (v0.2) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 구현 중 정한 설계 결정과 PRD 변경 사항 |
| [docs/DATA_POLICY.md](docs/DATA_POLICY.md) | 소스별 이용 조건 확인 결과와 수집기 규칙 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 데이터 흐름과 코드 위치 |
| [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) | 테이블, 시간 필드, 추가만 허용하는 이력 테이블 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 마일스톤과 체크포인트 |
| [docs/SOURCE_FEASIBILITY.md](docs/SOURCE_FEASIBILITY.md) | 수집 가능성 확인 절차와 결과 |

## 데이터에 대해

- **지금 수집하는 소스**: 공식 API가 있는 Bluesky(실시간 공개 스트림)와 Hacker News. 둘 다 영어권이라, 화면과 평가에서 어느 커뮤니티에서 관측된 것인지 밝힙니다.
- **나중에 추가할 소스**: 디시인사이드 미국주식갤러리, 네이버페이 증권 해외주식 토론. 공식 수집 경로가 없어 데이터 이용 문의 중입니다.
- 수집기는 읽기 전용·저빈도로 동작하고, 문제가 생기면 첫 번째에서 바로 멈추며, 작성자 정보는 해시로만 남기고, 출처에서 지워진 글은 원문을 지웁니다. 자세한 내용은 [DATA_POLICY.md](docs/DATA_POLICY.md)에 있습니다.
- **이 저장소에는 실제 게시글을 커밋하지 않습니다.** 수집 데이터는 로컬 `data/`에만 저장됩니다.

## 개발 환경

필요한 것: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 22+, pnpm 10.

```bash
make setup        # Python·웹 의존성 설치
cp .env.example .env
uv run nr db init # 로컬 DB 생성 (data/narrative_radar.db)

make dev-api      # API 서버 (http://127.0.0.1:8000)
make dev-web      # 웹앱 (http://127.0.0.1:5173, /api는 API 서버로 프록시)

make check        # 린트 + 테스트
```

수집 실행 방법과 확인 항목은 [docs/SOURCE_FEASIBILITY.md](docs/SOURCE_FEASIBILITY.md)에 있습니다.

```bash
uv run nr sources list                      # 소스별 상태와 수집 가능 여부
uv run nr collect hackernews --loop         # HN 수집
uv run nr collect bluesky                   # Bluesky 스트림 수집
uv run nr collect bluesky-metrics --loop    # Bluesky 지표 재방문
uv run nr sources report                    # 수집 현황 요약
```

## 구조

```text
backend/narrative_radar/   Python 백엔드 (FastAPI, SQLAlchemy, Anthropic SDK)
apps/web/                  React 웹앱 (Vite, TypeScript, Tailwind)
schemas/                   내보낸 JSON Schema
tests/                     단위·통합 테스트
docs/                      PRD, 결정 기록, 데이터 정책
data/                      로컬 DB와 수집 데이터 (커밋하지 않음)
```
