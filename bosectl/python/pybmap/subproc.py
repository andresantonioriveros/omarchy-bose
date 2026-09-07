"""Bounded child-process execution for device-influenced output.

`bluetoothctl` echoes device-set fields (Alias and friends), so its output
is untrusted input with a process attached. `subprocess.run` buffers stdout
and stderr without limit, letting one hostile or wedged reply grow the panel
bridge without bound. `run_capped` keeps the `CompletedProcess` shape callers
already handle but never retains more than `max_bytes` across both streams:
overflow kills the child and raises `OutputTooLarge`, which callers already
treat as failure because it subclasses `subprocess.SubprocessError`.
"""

import os
import selectors
import subprocess
import time

DEFAULT_MAX_BYTES = 65536
_READ_SIZE = 65536
_REAP_GRACE_SECONDS = 1


class OutputTooLarge(subprocess.SubprocessError):
    """A child produced more than max_bytes of output and was killed."""


def _decode(data):
    return bytes(data).decode("utf-8", "replace")


def _kill_and_reap(proc):
    if proc.poll() is not None:
        return
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=_REAP_GRACE_SECONDS)
    except (OSError, subprocess.SubprocessError):
        pass


def run_capped(argv, *, timeout, max_bytes=DEFAULT_MAX_BYTES):
    """Run argv like subprocess.run, retaining at most max_bytes of output.

    The cap applies to raw stdout and stderr bytes combined. Returned output
    is UTF-8 text with undecodable bytes replaced. Overflow and timeout both
    kill the child first; every wait remains bounded even if the child is
    wedged in uninterruptible I/O. Stdin is /dev/null so the child cannot
    block on inherited input.
    """
    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")

    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    streams = (proc.stdout, proc.stderr)
    buffers = {proc.stdout: bytearray(), proc.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout
    outcome = None

    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = "timeout"
                break
            events = selector.select(remaining)
            if not events:
                outcome = "timeout"
                break

            for key, _mask in events:
                stream = key.fileobj
                retained = sum(len(buffer) for buffer in buffers.values())
                read_size = min(_READ_SIZE, max_bytes - retained + 1)
                try:
                    piece = os.read(stream.fileno(), max(1, read_size))
                except BlockingIOError:
                    continue
                if not piece:
                    selector.unregister(stream)
                    continue

                available = max_bytes - retained
                buffers[stream].extend(piece[:available])
                if len(piece) > available:
                    outcome = "overflow"
                    break
            if outcome is not None:
                break

        if outcome is None:
            remaining = deadline - time.monotonic()
            try:
                proc.wait(timeout=max(0, remaining))
            except subprocess.TimeoutExpired:
                outcome = "timeout"

        if outcome is not None:
            _kill_and_reap(proc)
    except BaseException:
        _kill_and_reap(proc)
        raise
    finally:
        selector.close()
        for stream in streams:
            try:
                stream.close()
            except OSError:
                pass

    stdout = _decode(buffers[proc.stdout])
    stderr = _decode(buffers[proc.stderr])
    if outcome == "overflow":
        raise OutputTooLarge(argv)
    if outcome == "timeout":
        raise subprocess.TimeoutExpired(
            argv, timeout, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(argv, proc.returncode, stdout, stderr)
