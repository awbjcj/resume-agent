"""Typed Gmail failure family. `.code` feeds run error_code and ApiException."""


class GmailError(Exception):
    code = "GMAIL_ERROR"


class GmailNotConnected(GmailError):
    """No token, or the stored token can no longer be refreshed."""

    code = "GMAIL_NOT_CONNECTED"


class GmailScopeMissing(GmailError):
    """Token lacks a required Gmail scope — reconnect and approve it.

    Raised at connect time when the grant carries no gmail.readonly at all, and
    at draft time when it carries no gmail.compose.
    """

    code = "GMAIL_SCOPE_MISSING"


class GmailApiError(GmailError):
    """Quota/5xx/transport failure from the Gmail API."""

    code = "GMAIL_API_ERROR"
