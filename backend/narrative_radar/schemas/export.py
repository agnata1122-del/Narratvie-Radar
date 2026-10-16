"""Pydantic 스키마를 JSON Schema로 내보낸다. 결과는 저장소의 schemas/에 커밋한다."""

import json
from pathlib import Path

from pydantic import BaseModel

from narrative_radar.schemas.classification import ClassificationOutput, ClassificationRecord
from narrative_radar.schemas.document import DocumentIn
from narrative_radar.schemas.events import GraphEventOut
from narrative_radar.schemas.profile import InterestProfileConfig
from narrative_radar.schemas.views import SavedViewIn

EXPORTS: dict[str, type[BaseModel]] = {
    "classification_output": ClassificationOutput,
    "classification_record": ClassificationRecord,
    "document": DocumentIn,
    "graph_event": GraphEventOut,
    "interest_profile": InterestProfileConfig,
    "saved_view": SavedViewIn,
}


def render(model: type[BaseModel]) -> str:
    return (
        json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def write_all(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(render(model), encoding="utf-8")
        written.append(path)
    return written
