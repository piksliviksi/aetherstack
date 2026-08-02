#!/usr/bin/env python3
"""The run-cancellation registry server.py exposes to execute_auto/execute_service/execute_graph."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402


def test_unregistered_run_id_reports_not_found_and_never_cancels() -> None:
    check = server._make_cancel_check("never-registered")
    assert check() is False
    assert server._cancel_run("never-registered") is False


def test_cancel_flips_the_check_a_registered_run_sees() -> None:
    server._register_run("run-1")
    try:
        check = server._make_cancel_check("run-1")
        assert check() is False
        assert server._cancel_run("run-1") is True
        assert check() is True
    finally:
        server._unregister_run("run-1")


def test_unregister_clears_state_so_a_stale_run_id_cannot_be_cancelled_later() -> None:
    server._register_run("run-2")
    server._unregister_run("run-2")
    assert server._cancel_run("run-2") is False
    assert server._make_cancel_check("run-2")() is False


def test_cancelling_one_run_does_not_affect_another() -> None:
    server._register_run("run-a")
    server._register_run("run-b")
    try:
        server._cancel_run("run-a")
        assert server._make_cancel_check("run-a")() is True
        assert server._make_cancel_check("run-b")() is False
    finally:
        server._unregister_run("run-a")
        server._unregister_run("run-b")
