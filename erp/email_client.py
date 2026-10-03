import logging
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from erp import config

log = logging.getLogger(__name__)


class EmailError(Exception):
    pass


@dataclass
class SendResult:
    ok: bool
    error: str | None = None
    skipped: bool = False


class EmailClient:
    """Thin SMTP client supporting STARTTLS or implicit SSL, with retries."""

    def __init__(
        self,
        host: str = config.SMTP_HOST,
        port: int = config.SMTP_PORT,
        username: str = config.SMTP_USER,
        password: str = config.SMTP_PASSWORD,
        sender: str = config.SMTP_FROM,
        use_ssl: bool = config.SMTP_USE_SSL,
        enabled: bool = config.EMAIL_ENABLED,
        timeout: float = 20.0,
        retries: int = 2,
        retry_delay: float = 1.5,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender or username
        self.use_ssl = use_ssl
        self.enabled = enabled
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    def build_message(self, to: list[str], subject: str, html: str, text: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid()
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        return msg

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.use_ssl:
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=context)
                server.ehlo()
        if self.username and self.password:
            server.login(self.username, self.password)
        return server

    def send(self, to: list[str] | str, subject: str, html: str, text: str) -> SendResult:
        recipients = [to] if isinstance(to, str) else [r for r in to if r]
        if not recipients:
            return SendResult(ok=False, error="No recipients")
        if not self.enabled:
            log.info("Email disabled; skipping send to %s: %s", recipients, subject)
            return SendResult(ok=True, skipped=True)
        if not self.configured:
            return SendResult(ok=False, error="SMTP is not configured (set SMTP_HOST and SMTP_FROM)")

        msg = self.build_message(recipients, subject, html, text)
        last_error = ""
        for attempt in range(self.retries + 1):
            try:
                with self._connect() as server:
                    server.send_message(msg)
                return SendResult(ok=True)
            except (smtplib.SMTPException, OSError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("Email send attempt %d failed: %s", attempt + 1, last_error)
                # Authentication and recipient errors will not fix themselves on retry.
                if isinstance(exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused)):
                    break
                if attempt < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        return SendResult(ok=False, error=last_error)
