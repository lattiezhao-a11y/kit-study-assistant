"""Open a verified TLS connection to an IMAP server."""

import imaplib
import ssl


def connect(host: str, port: int = 993, *, timeout: int) -> imaplib.IMAP4_SSL:
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(),
                           timeout=timeout)
