"""Fixed shared category vocabulary for profile and constellation display."""

from __future__ import annotations

from typing import Literal

SKILL_GROUPS: dict[str, str] = {
    "languages": "Programming Languages",
    "frontend-web": "Frontend & Web",
    "backend-apis": "Backend & APIs",
    "mobile-desktop": "Mobile & Desktop",
    "data-engineering": "Data Engineering & Analytics",
    "ai-ml": "AI & Machine Learning",
    "databases-storage": "Databases & Storage",
    "cloud-infra": "Cloud & Infrastructure",
    "devops-automation": "DevOps & Automation",
    "testing-quality": "Testing & Quality",
    "security-compliance": "Security & Compliance",
    "systems-embedded": "Systems & Embedded",
    "architecture-design": "Architecture & Design",
    "tools-platforms": "Tools & Platforms",
    "leadership-management": "Leadership & Management",
    "collaboration-communication": "Collaboration & Communication",
    "product-business": "Product & Business",
    "process-methodology": "Process & Methodology",
    "domain-knowledge": "Domain Knowledge",
    "other": "Other",
}

SOFT_CATEGORY_SLUGS: frozenset[str] = frozenset(
    {
        "leadership-management",
        "collaboration-communication",
        "product-business",
        "process-methodology",
        "domain-knowledge",
    }
)

LEGACY_GROUP_REMAP: dict[str, str] = {
    "security": "security-compliance",
    "leadership": "leadership-management",
    "communication": "collaboration-communication",
    "devops-tooling": "devops-automation",
    "databases": "databases-storage",
}
# Note: the old "data-ml", "frameworks", and "practices" slugs are intentionally
# NOT remapped. Each split across several new slugs, so a deterministic 1:1
# upgrade would miscategorize; they are dropped on load and re-classified by the
# incremental LLM pass (classify_missing_groups) on the next profile build.


def category_kind(slug: str) -> Literal["hard", "soft"]:
    """Return the display kind for a validated category slug."""
    return "soft" if slug in SOFT_CATEGORY_SLUGS else "hard"
