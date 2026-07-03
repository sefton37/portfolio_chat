"""Regression tests for SMTP header (CRLF) injection in the contact mailer.

Origin: a security-review probe on 2026-07-02 submitted a contact message with
``sender_name = "Test\\nBcc: attacker@evil.com"``. Because the mailer wrote
``sender_name`` straight into the ``Subject:`` header and sends via
``sendmail -t`` (which reads recipients FROM the headers), the embedded newline
split the header, ``Bcc: attacker@evil.com`` became a real header, and postfix
relayed a copy off-box. These tests pin the fix: any CR/LF in a user-controlled
field that reaches a header must be neutralized so no extra recipient header can
be smuggled in (CWE-93).
"""

from __future__ import annotations

from portfolio_chat.contact.sweeper import CONTACT_RECIPIENT, _format_email


def _headers_of(rendered: str) -> list[str]:
    """Return the header lines (everything before the first blank line)."""
    headers, _, _ = rendered.partition("\n\n")
    return headers.split("\n")


def _has_recipient_injection(rendered: str) -> bool:
    """True if any header line smuggles a To/Cc/Bcc recipient header.

    A header line is a field only when the field name starts the line. The
    intended ``To:`` header (to CONTACT_RECIPIENT) is allowed; anything else is
    an injection.
    """
    for line in _headers_of(rendered):
        low = line.lower()
        if low.startswith(("bcc:", "cc:")):
            return True
        if low.startswith("to:") and line.strip() != f"To: {CONTACT_RECIPIENT}":
            return True
    return False


def test_newline_in_sender_name_does_not_inject_bcc() -> None:
    """The canonical probe: LF + 'Bcc:' in sender_name must not add a header."""
    rendered = _format_email(
        {
            "id": "testinj123abc",
            "timestamp": "2026-07-03T00:46:12Z",
            "message": "Testing header injection vulnerability",
            "sender_name": "Test\nBcc: attacker@evil.com",
            "sender_email": "test@example.com",
        }
    )
    assert not _has_recipient_injection(rendered)
    # Subject stays a single header line (the newline was neutralized).
    subject_lines = [h for h in _headers_of(rendered) if h.startswith("Subject:")]
    assert len(subject_lines) == 1
    assert "\n" not in subject_lines[0]


def test_crlf_in_sender_name_does_not_inject() -> None:
    """A full CRLF (\\r\\n) sequence must also be neutralized."""
    rendered = _format_email(
        {
            "id": "x",
            "timestamp": "2026-07-03T00:00:00Z",
            "message": "hi",
            "sender_name": "Eve\r\nBcc: attacker@evil.com\r\nCc: also@evil.com",
        }
    )
    assert not _has_recipient_injection(rendered)


def test_bare_cr_in_sender_name_does_not_inject() -> None:
    """A lone CR (\\r), which some MTAs treat as a line break, is stripped."""
    rendered = _format_email(
        {
            "id": "x",
            "timestamp": "2026-07-03T00:00:00Z",
            "message": "hi",
            "sender_name": "Eve\rBcc: attacker@evil.com",
        }
    )
    assert not _has_recipient_injection(rendered)


def test_newline_in_sender_email_does_not_inject_reply_to() -> None:
    """sender_email feeds Reply-To; a smuggled Bcc there must be neutralized."""
    rendered = _format_email(
        {
            "id": "x",
            "timestamp": "2026-07-03T00:00:00Z",
            "message": "hi",
            "sender_email": "test@example.com\nBcc: attacker@evil.com",
        }
    )
    assert not _has_recipient_injection(rendered)
    reply_to = [h for h in _headers_of(rendered) if h.startswith("Reply-To:")]
    assert len(reply_to) == 1
    assert "\n" not in reply_to[0] and "\r" not in reply_to[0]


def test_only_intended_recipient_header_present() -> None:
    """Exactly one recipient header (the intended To:) even under attack."""
    rendered = _format_email(
        {
            "id": "x",
            "timestamp": "2026-07-03T00:00:00Z",
            "message": "hi",
            "sender_name": "A\nTo: victim@example.com",
            "sender_email": "b@example.com\nBcc: attacker@evil.com",
        }
    )
    recipient_headers = [
        h for h in _headers_of(rendered) if h.lower().startswith(("to:", "cc:", "bcc:"))
    ]
    assert recipient_headers == [f"To: {CONTACT_RECIPIENT}"]


def test_benign_message_still_renders_correctly() -> None:
    """The fix must not break normal, non-malicious submissions."""
    rendered = _format_email(
        {
            "id": "abc123",
            "timestamp": "2026-07-03T00:00:00Z",
            "message": "Hello, I liked your portfolio.",
            "sender_name": "Jane Doe",
            "sender_email": "jane@example.com",
        }
    )
    headers = _headers_of(rendered)
    assert f"To: {CONTACT_RECIPIENT}" in headers
    assert "Subject: Portfolio contact from Jane Doe" in headers
    assert "Reply-To: jane@example.com" in headers
    assert not _has_recipient_injection(rendered)
