#!/usr/bin/env python3
"""BoundedThreadingHTTPServer: the accept loop must never block."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


class _FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def _make_server(max_threads: int) -> server.BoundedThreadingHTTPServer:
    # Build the instance without binding a real socket: __init__ only needs
    # server_address/request_handler_class for ThreadingHTTPServer's own
    # setup, which we bypass entirely by constructing _request_slots directly.
    instance = server.BoundedThreadingHTTPServer.__new__(server.BoundedThreadingHTTPServer)
    instance._request_slots = threading.BoundedSemaphore(max_threads)
    return instance


def test_process_request_closes_the_socket_immediately_when_slots_are_exhausted() -> None:
    inst = _make_server(max_threads=1)
    inst._request_slots.acquire()  # simulate the one slot already being held
    fake = _FakeSocket()
    with mock.patch.object(server.ThreadingHTTPServer, "process_request") as parent:
        inst.process_request(fake, ("127.0.0.1", 12345))
    assert fake.closed is True
    parent.assert_not_called()


def test_process_request_proceeds_normally_when_a_slot_is_available() -> None:
    inst = _make_server(max_threads=1)
    fake = _FakeSocket()
    with mock.patch.object(server.ThreadingHTTPServer, "process_request") as parent:
        inst.process_request(fake, ("127.0.0.1", 12345))
    assert fake.closed is False
    parent.assert_called_once()
    # process_request itself does not release - process_request_thread does,
    # once the request actually finishes (see BoundedThreadingHTTPServer).
    assert inst._request_slots.acquire(blocking=False) is False  # the one slot is still held


def test_process_request_releases_the_slot_if_the_parent_call_raises() -> None:
    inst = _make_server(max_threads=1)
    fake = _FakeSocket()
    with mock.patch.object(server.ThreadingHTTPServer, "process_request", side_effect=RuntimeError("boom")):
        try:
            inst.process_request(fake, ("127.0.0.1", 12345))
            assert False, "expected the exception to propagate"
        except RuntimeError:
            pass
    # released back, so a subsequent request can still acquire it
    assert inst._request_slots.acquire(blocking=False) is True


def test_process_request_thread_releases_its_slot_when_the_request_completes() -> None:
    inst = _make_server(max_threads=1)
    inst._request_slots.acquire()
    with mock.patch.object(server.ThreadingHTTPServer, "process_request_thread"):
        inst.process_request_thread(_FakeSocket(), ("127.0.0.1", 12345))
    assert inst._request_slots.acquire(blocking=False) is True
