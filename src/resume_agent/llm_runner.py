from typing import Any, Protocol


class Runner(Protocol):
    """Minimal callable surface the pipeline expects from an LLM agent."""

    def run(self, prompt: str) -> Any: ...


class AgentRunner:
    """Adapter that narrows third-party agent APIs to ``run(prompt: str)``."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    def run(self, prompt: str) -> Any:
        return self._agent.run(prompt)
