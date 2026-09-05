"""Tests for pybmap.subproc — bounded child-process execution."""

import subprocess
import sys

import pytest

from pybmap.subproc import OutputTooLarge, run_capped


def test_passthrough_returncode_and_streams():
    result = run_capped(
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == "out\n"
    assert result.stderr == "err\n"


def test_passthrough_nonzero_exit():
    result = run_capped(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        timeout=10,
    )
    assert result.returncode == 3


def test_exactly_at_cap_is_fine():
    result = run_capped(
        [sys.executable, "-c", "import sys; sys.stdout.write('A' * 100)"],
        timeout=10,
        max_bytes=100,
    )
    assert result.stdout == "A" * 100


def test_one_byte_over_cap_kills_and_raises():
    with pytest.raises(OutputTooLarge):
        run_capped(
            [sys.executable, "-c", "import sys; sys.stdout.write('A' * 101)"],
            timeout=10,
            max_bytes=100,
        )


def test_gushing_stdout_is_capped():
    with pytest.raises(OutputTooLarge):
        run_capped(
            [sys.executable, "-c", "import sys; sys.stdout.write('A' * 5000000)"],
            timeout=10,
        )


def test_gushing_both_pipes_cannot_deadlock():
    # Both pipes full at once: the child blocks writing until killed, so
    # completing at all proves the kill path drains both sides.
    with pytest.raises(OutputTooLarge):
        run_capped(
            [
                sys.executable,
                "-c",
                "import sys; "
                "sys.stdout.write('A' * 5000000); "
                "sys.stderr.write('B' * 5000000)",
            ],
            timeout=10,
        )


def test_timeout_still_fires_with_partial_output():
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_capped(
            [
                sys.executable,
                "-c",
                "import sys, time; print('part', flush=True); time.sleep(30)",
            ],
            timeout=1,
        )
    assert caught.value.output == "part\n"


def test_undecodable_bytes_degrade_instead_of_raising():
    result = run_capped(
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe' * 64)"],
        timeout=10,
    )
    assert "\ufffd" in result.stdout


def test_missing_executable_raises_filenotfound():
    with pytest.raises(FileNotFoundError):
        run_capped(["/nonexistent/omabose-test-binary"], timeout=5)


def test_output_too_large_is_a_subprocess_error():
    assert issubclass(OutputTooLarge, subprocess.SubprocessError)
