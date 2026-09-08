"""Tests for pybmap.subproc — bounded child-process execution."""

import subprocess
import sys
import time

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


def test_cap_counts_utf8_bytes_not_characters():
    with pytest.raises(OutputTooLarge):
        run_capped(
            [sys.executable, "-c", "import sys; sys.stdout.write('\u00e9' * 60)"],
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
                "import sys, threading; "
                "a = threading.Thread(target=lambda: sys.stdout.write('A' * 5000000)); "
                "b = threading.Thread(target=lambda: sys.stderr.write('B' * 5000000)); "
                "a.start(); b.start(); a.join(); b.join()",
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


def test_timeout_partials_stay_within_cap():
    with pytest.raises(subprocess.TimeoutExpired) as caught:
        run_capped(
            [
                sys.executable,
                "-c",
                "import sys, time; sys.stdout.write('P' * 50); "
                "sys.stdout.flush(); time.sleep(30)",
            ],
            timeout=1,
            max_bytes=100,
        )
    assert caught.value.output == "P" * 50


def test_timeout_applies_after_child_closes_its_pipes():
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_capped(
            [
                sys.executable,
                "-c",
                "import os, time; os.close(1); os.close(2); time.sleep(30)",
            ],
            timeout=0.2,
        )
    assert time.monotonic() - start < 2


@pytest.mark.skipif(sys.platform == "win32", reason="requires fork")
def test_inherited_pipe_does_not_block_cleanup():
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_capped(
            [
                sys.executable,
                "-c",
                "import os, time; "
                "pid = os.fork(); "
                "time.sleep(2) if pid == 0 else None",
            ],
            timeout=0.2,
        )
    assert time.monotonic() - start < 2


def test_overflow_wins_when_writer_stays_alive():
    with pytest.raises(OutputTooLarge):
        run_capped(
            [
                sys.executable,
                "-c",
                "import sys, time; "
                "sys.stdout.buffer.write(b'A' * 101); "
                "sys.stdout.flush(); time.sleep(30)",
            ],
            timeout=2,
            max_bytes=100,
        )


def test_interruption_kills_child(monkeypatch):
    children = []
    real_popen = subprocess.Popen

    def record_child(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr("pybmap.subproc.subprocess.Popen", record_child)

    class InterruptedSelector:
        def register(self, *_args):
            pass

        def get_map(self):
            return {1: object()}

        def select(self, _timeout):
            raise KeyboardInterrupt

        def close(self):
            pass

    monkeypatch.setattr(
        "pybmap.subproc.selectors.DefaultSelector", InterruptedSelector
    )

    with pytest.raises(KeyboardInterrupt):
        run_capped(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=10,
        )
    assert children[0].poll() is not None


def test_stdin_is_devnull():
    result = run_capped(
        [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"],
        timeout=10,
    )
    assert result.stdout == "''\n"


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
