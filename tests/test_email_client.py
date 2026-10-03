import smtplib
from unittest.mock import MagicMock, patch

from erp.email_client import EmailClient


def _client(**kw):
    defaults = dict(host="smtp.test", port=587, username="u", password="p", sender="erp@test.com",
                    use_ssl=False, enabled=True, retries=1, retry_delay=0)
    defaults.update(kw)
    return EmailClient(**defaults)


def test_send_uses_starttls_and_login():
    server = MagicMock()
    server.has_extn.return_value = True
    server.__enter__.return_value = server
    with patch("erp.email_client.smtplib.SMTP", return_value=server) as smtp:
        result = _client().send("to@test.com", "Hi", "<p>Hi</p>", "Hi")
    assert result.ok
    smtp.assert_called_once_with("smtp.test", 587, timeout=20.0)
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("u", "p")
    msg = server.send_message.call_args[0][0]
    assert msg["To"] == "to@test.com" and msg["Subject"] == "Hi"
    assert msg.is_multipart()


def test_send_retries_then_fails():
    with patch("erp.email_client.smtplib.SMTP", side_effect=smtplib.SMTPServerDisconnected("down")) as smtp:
        result = _client(retries=2).send("to@test.com", "Hi", "<p>Hi</p>", "Hi")
    assert not result.ok and "down" in result.error
    assert smtp.call_count == 3


def test_auth_error_not_retried():
    with patch("erp.email_client.smtplib.SMTP", side_effect=smtplib.SMTPAuthenticationError(535, b"bad")) as smtp:
        result = _client(retries=3).send("to@test.com", "Hi", "<p>Hi</p>", "Hi")
    assert not result.ok
    assert smtp.call_count == 1


def test_disabled_skips():
    with patch("erp.email_client.smtplib.SMTP") as smtp:
        result = _client(enabled=False).send("to@test.com", "Hi", "<p>Hi</p>", "Hi")
    assert result.ok and result.skipped
    smtp.assert_not_called()


def test_unconfigured_fails_cleanly():
    result = _client(host="").send("to@test.com", "Hi", "<p>Hi</p>", "Hi")
    assert not result.ok and "not configured" in result.error
