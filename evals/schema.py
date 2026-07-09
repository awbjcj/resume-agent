from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts

TrapKind = Literal[
    "missing_skill",
    "adjacent_skill",
    "inflatable_metric",
    "seniority_inflation",
]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class Trap(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    kind: TrapKind
    forbidden_terms: list[NonEmptyStr] = Field(min_length=1)
    description: NonEmptyStr
    probe_claim: NonEmptyStr
    probe_provenance: NonEmptyStr


class EvalCase(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    profile_ref: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    target: Literal["resume", "cover_letter"] = "resume"
    jd_text: str
    criteria: JobCriteria | None = None
    traps: list[Trap] = Field(default_factory=list)
    must_cite: list[str] = Field(default_factory=list)
    rubric: list[NonEmptyStr] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_labels(self) -> "EvalCase":
        if len({trap.id for trap in self.traps}) != len(self.traps):
            raise ValueError("trap ids must be unique within a case")
        if len(set(self.rubric)) != len(self.rubric):
            raise ValueError("rubric dimensions must be unique")
        return self


def load_case(path: Path) -> EvalCase:
    return EvalCase.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_cases(directory: Path) -> list[EvalCase]:
    return [load_case(path) for path in sorted(Path(directory).glob("*.json"))]


def load_profile(case: EvalCase, profiles_dir: Path) -> ProfileFacts:
    path = Path(profiles_dir) / f"{case.profile_ref}.json"
    return ProfileFacts.model_validate_json(path.read_text(encoding="utf-8"))
