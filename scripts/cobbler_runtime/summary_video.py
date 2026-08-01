"""Build a structured summary-video storyboard from run artifacts (AIG-369)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class SummaryScene:
    title: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def build_summary_storyboard(
    *,
    mission: str,
    batches: Sequence[tuple[str, str]],
    residual_risks: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a Remotion/HyperFrames-ready storyboard dict (no binary render)."""
    scenes = [SummaryScene(title="Mission", body=mission.strip() or "(none)")]
    for batch_id, summary in batches:
        scenes.append(SummaryScene(title=batch_id, body=summary.strip() or "(no summary)"))
    if residual_risks:
        scenes.append(
            SummaryScene(
                title="Residual risks",
                body="\n".join(f"- {r}" for r in residual_risks),
            )
        )
    scenes.append(SummaryScene(title="Done", body="Elves run complete."))
    return {
        "format": "elves-summary-storyboard-v1",
        "engine_hints": ["hyperframes", "remotion"],
        "scenes": [s.to_dict() for s in scenes],
    }
