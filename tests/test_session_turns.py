"""Shared turn formatting: one retry on rejection, type-checked output."""

import pytest

from resume_agent.sessions.turns import TurnRejected, format_with_retry


class _Out:
    def __init__(self, value: str):
        self.value = value


class _Formatter:
    def __init__(self, outputs):
        self._outputs = list(outputs)
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)

        class _Resp:
            content = self._outputs.pop(0)

        return _Resp()


def test_happy_path_formats_once():
    formatter = _Formatter([_Out("ok")])
    result = format_with_retry(
        formatter, "raw notes", _Out, lambda out: out, label="COACH NOTES"
    )
    assert result.value == "ok"
    assert formatter.prompts == ["COACH NOTES (UNTRUSTED):\nraw notes"]


def test_wrong_type_raises_typeerror():
    formatter = _Formatter(["not the schema"])
    with pytest.raises(TypeError, match="Expected _Out"):
        format_with_retry(formatter, "n", _Out, lambda out: out, label="X")


def test_rejection_retries_once_with_feedback():
    formatter = _Formatter([_Out("bad"), _Out("good")])

    def validate(out):
        if out.value == "bad":
            raise TurnRejected("quote missing")
        return out

    result = format_with_retry(formatter, "n", _Out, validate, label="INTERVIEWER NOTES")
    assert result.value == "good"
    assert "PREVIOUS OUTPUT REJECTED: quote missing" in formatter.prompts[1]


def test_second_rejection_propagates():
    formatter = _Formatter([_Out("bad"), _Out("bad")])

    def validate(out):
        raise TurnRejected("still wrong")

    with pytest.raises(TurnRejected):
        format_with_retry(formatter, "n", _Out, validate, label="X")


def test_turn_rejected_is_one_class_everywhere():
    from resume_agent.interview.agent import TurnRejected as interview_cls
    from resume_agent.profile.coach import TurnRejected as coach_cls

    assert coach_cls is TurnRejected
    assert interview_cls is TurnRejected


def test_missing_model_keys_labels(monkeypatch):
    from resume_agent import llm_runner
    from resume_agent.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model: None)
    labels = llm_runner.missing_model_keys(settings)
    assert labels == [
        f"mid ({settings.mid_model})",
        f"cheap ({settings.cheap_model})",
    ]
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model: "key")
    assert llm_runner.missing_model_keys(settings) == []
