# Narrative Radar

**From fragmented conversations to evolving intelligence.**

관심사 하나(첫 대상: NVIDIA)를 등록하면, 선택한 커뮤니티에서 관측된 주장과 이슈를 지식 그래프로 묶고, 그 관계가 시간에 따라 어떻게 달라지는지를 근거와 함께 보여주는 웹앱입니다.

미래를 예측하는 도구가 아니라, 지금 일어나고 있지만 놓치기 쉬운 변화를 발견하는 도구입니다. 이 앱이 보여주는 내용은 투자 조언이 아닙니다.

> **현재 상태: 개발 초기 (v0.2, M1 진행 중).** 라이브 수집은 꺼져 있습니다. 진행 상황은 [docs/ROADMAP.md](docs/ROADMAP.md)를 보세요.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 제품 요구사항 원문 (v0.2) |
| [docs/DECISIONS.md](docs/DECISIONS.md) | 구현 중 정한 설계 결정과 PRD 변경 사항 |
| [docs/DATA_POLICY.md](docs/DATA_POLICY.md) | 소스별 이용 조건 확인 결과와 수집기 규칙 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 데이터 흐름과 코드 위치 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 마일스톤과 체크포인트 |

## 데이터에 대해

- 수집 대상: 디시인사이드 미국주식갤러리, 네이버페이 증권 해외주식 토론(NVDA).
- 두 소스 모두 공식적으로 허가된 자동 수집 경로가 없습니다. 자세한 확인 결과와 수집기가 지키는 규칙(읽기 전용, 저빈도, 차단 시 자동 중단, 작성자 정보 비저장)은 [DATA_POLICY.md](docs/DATA_POLICY.md)에 있습니다.
- **이 저장소에는 실제 게시글을 커밋하지 않습니다.** 수집 데이터는 로컬 `data/`에만 저장됩니다.

## 개발 환경

필요한 것: Python 3.13+, [uv](https://docs.astral.sh/uv/), Node 22+, pnpm 10.

```bash
make setup        # Python·웹 의존성 설치
cp .env.example .env

make dev-api      # API 서버 (http://127.0.0.1:8000)
make dev-web      # 웹앱 (http://127.0.0.1:5173, /api는 API 서버로 프록시)

make check        # 린트 + 테스트
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
