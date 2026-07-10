from resume_agent.api.schemas.sources import SourceOut, SourcePreviewOut
from resume_agent.discovery.connectors.sources import SourceView
from resume_agent.services.sources import SourcePreview


def test_source_out_projects_view_with_camel_alias():
    view = SourceView(
        id="greenhouse:x",
        kind="greenhouse",
        type="board",
        display_name="X",
        enabled=True,
        pullable=True,
        detail="x",
    )

    dumped = SourceOut.model_validate(view).model_dump(by_alias=True)

    assert dumped["displayName"] == "X"
    assert dumped["pullable"] is True
    assert dumped["type"] == "board"


def test_source_out_projects_optional_limit():
    view = SourceView(
        id="remoteok",
        kind="remoteok",
        type="aggregator",
        display_name="RemoteOK",
        enabled=True,
        pullable=True,
        detail="aggregator",
        limit=12,
    )
    assert SourceOut.model_validate(view).model_dump(by_alias=True)["limit"] == 12


def test_preview_out_projects_dataclass():
    preview = SourcePreview(ok=True, url="u", kind="greenhouse", token="x", role_count=3)

    dumped = SourcePreviewOut.model_validate(preview).model_dump(by_alias=True)

    assert dumped["roleCount"] == 3
