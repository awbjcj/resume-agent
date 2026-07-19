import base64

from resume_agent.gmail.classify import hydrating_classifier
from resume_agent.gmail.client import EmailMessage, extract_body, fetch_message_body


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _payload_plain(text: str) -> dict:
    return {"mimeType": "text/plain", "body": {"data": _b64(text)}}


def test_extract_body_prefers_text_plain_in_multipart():
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML version</p>")}},
            _payload_plain("plain version"),
        ],
    }
    assert extract_body(payload) == "plain version"


def test_extract_body_falls_back_to_html():
    payload = {"mimeType": "text/html", "body": {"data": _b64("<p>Hello <b>there</b></p>")}}
    assert "Hello" in extract_body(payload)
    assert "<p>" not in extract_body(payload)


def test_extract_body_truncates():
    payload = _payload_plain("x" * 10_000)
    assert len(extract_body(payload)) <= 4000


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload

    def get(self, userId, id, format):
        payload = self._payload
        return type("Req", (), {"execute": staticmethod(lambda: {"payload": payload})})()


class _FakeService:
    def __init__(self, payload):
        self._messages = _FakeMessages(payload)

    def users(self):
        messages = self._messages
        return type("Users", (), {"messages": staticmethod(lambda: messages)})()


def test_fetch_message_body_via_service():
    service = _FakeService(_payload_plain("Unfortunately we will not proceed."))
    assert "Unfortunately" in fetch_message_body(service, "m1")


def test_hydrating_classifier_uses_body_rules():
    service = _FakeService(_payload_plain("Unfortunately we chose other candidates."))
    classify = hydrating_classifier(service, llm=None)
    email = EmailMessage(
        sender="hr@acme.com",
        sender_domain="acme.com",
        subject="Your application",
        snippet="Update on your application",
        message_id="m1",
    )
    assert classify(email) == "rejection"
    assert email.body is not None  # hydrated in place, fetched once
