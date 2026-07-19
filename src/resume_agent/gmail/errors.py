"""Typed Gmail failure family. `.code` feeds run error_code and ApiException."""


class GmailError(Exception):
    code = "GMAIL_ERROR"


class GmailNotConnected(GmailError):
    """No token, or the stored token can no longer be refreshed."""

    code = "GMAIL_NOT_CONNECTED"


class GmailScopeMissing(GmailError):
    """Token lacks gmail.compose — reconnect to enable drafts."""

    code = "GMAIL_SCOPE_MISSING"


class GmailApiError(GmailError):
    """Quota/5xx/transport failure from the Gmail API."""

    code = "GMAIL_API_ERROR"
