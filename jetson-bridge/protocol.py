"""Wire protocol between the MP257 (client) and the Jetson Nano (server).

Every message on the TCP stream is one *envelope*::

    +----------------+----------------+-------------+--------------+
    | header_len u32 | payload_len u32| header JSON | payload bytes|
    +----------------+----------------+-------------+--------------+
      big-endian       big-endian       UTF-8         raw (JPEG)

Why this framing: TCP is a byte stream with no message boundaries, so we need
a length prefix to know where each message ends. The header stays JSON (easy
to read and debug, as the project convention says) while the image travels as
raw bytes: base64-encoding a JPEG inside JSON would add ~33 % bandwidth and CPU
for nothing.

Message types are documented in docs/protocol.md.
"""
from __future__ import annotations

import json
import socket
import struct
from typing import Any

PROTOCOL_VERSION = 1

MAX_HEADER_BYTES = 64 * 1024
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024  # one JPEG frame; bigger means a bug or an attack

_PREFIX = struct.Struct(">II")

# Message types
HELLO = "hello"
HELLO_ACK = "hello_ack"
PING = "ping"
PONG = "pong"
FRAME = "frame"
DETECTIONS = "detections"


class ProtocolError(Exception):
    """The peer sent something that is not valid protocol."""


class ConnectionClosed(Exception):
    """The peer closed the connection (cleanly or not)."""


def encode(header: dict[str, Any], payload: bytes = b"") -> bytes:
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_HEADER_BYTES or len(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolError("message too large")
    return _PREFIX.pack(len(raw), len(payload)) + raw + payload


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """recv() may return fewer bytes than asked; loop until we have all n."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionClosed("peer closed the connection")
        buf += chunk
    return bytes(buf)


def read_message(sock: socket.socket) -> tuple[dict[str, Any], bytes]:
    """Block until one full envelope arrives. Raises socket.timeout, OSError,
    ConnectionClosed or ProtocolError."""
    header_len, payload_len = _PREFIX.unpack(_recv_exact(sock, _PREFIX.size))
    # Validate lengths BEFORE allocating, so a corrupt prefix can't make us
    # try to read gigabytes.
    if header_len == 0 or header_len > MAX_HEADER_BYTES or payload_len > MAX_PAYLOAD_BYTES:
        raise ProtocolError(f"bad lengths: header={header_len} payload={payload_len}")
    raw = _recv_exact(sock, header_len)
    payload = _recv_exact(sock, payload_len) if payload_len else b""
    try:
        header = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid header JSON: {exc}") from exc
    if not isinstance(header, dict) or not isinstance(header.get("type"), str):
        raise ProtocolError("header must be an object with a string 'type'")
    return header, payload


def send_message(sock: socket.socket, header: dict[str, Any], payload: bytes = b"") -> None:
    sock.sendall(encode(header, payload))
