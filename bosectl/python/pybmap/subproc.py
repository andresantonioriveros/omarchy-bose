"""Bounded child-process execution for device-influenced output.

`bluetoothctl` echoes device-set fields (Alias and friends), so its output
is untrusted input with a process attached. `subprocess.run` buffers stdout
and stderr without limit, letting one hostile or wedged reply grow the panel
bridge without bound. `run_capped` keeps the `CompletedProcess` shape callers
already handle but never retains more than `max_bytes` across both streams:
overflow kills the child and raises `OutputTooLarge`, which callers already
treat as failure because it subclasses `subprocess.SubprocessError`.
"""

import subprocess
import threading
import time

DEFAULT_MAX_BYTES = 65536


class OutputTooLarge(subprocess.SubprocessError):
    """A child produced more than max_bytes of output and was killed."""


def run_capped(argv, *, timeout, max_bytes=DEFAULT_MAX_BYTES):
    """Run argv like subprocess.run, capping retained output at max_bytes.

    Returns subprocess.CompletedProcess with text stdout/stderr. Raises
    OutputTooLarge when the child exceeds the cap (child is killed first),
    subprocess.TimeoutExpired past timeout (also killed first), and
    FileNotFoundError when the executable is missing -- the same failures
    callers already map to their fail-closed paths. Undecodable bytes are
    replaced rather than raising, so hostile output degrades to mojibake
    instead of crashing the bridge.

    The cap counts decoded characters across both streams combined, so a
    flood cannot dodge it by splitting across stdout and stderr. Retained
    output never exceeds max_bytes on any path: a chunk is kept only when
    the running total stays within the cap afterwards, so anything bigger
    trips overflow first -- this holds for returned payloads and for the
    partials carried by TimeoutExpired alike, and neither caller parses
    the latter anyway. Stdin is /dev/null, so a child can neither block
    on input nor inherit a terminal. Every wait after a kill is itself
    bounded: a child wedged in uninterruptible Bluetooth I/O ignores
    SIGKILL, and the caller must still get its exception instead of
    hanging with it (drain threads are daemon, so abandoning them cannot
    block interpreter teardown).
    """
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    buffers = {proc.stdout: [], proc.stderr: []}
    state = {"total": 0, "overflow": False}
    lock = threading.Lock()

    def _drain(pipe):
        while True:
            try:
                piece = pipe.read(65536)
            except (OSError, ValueError):
                # Our own close from the teardown below racing a blocked
                # read (wedged child): end quietly instead of noisily.
                return
            if not piece:
                return
            with lock:
                state["total"] += len(piece)
                if state["total"] > max_bytes:
                    state["overflow"] = True
                else:
                    buffers[pipe].append(piece)
            if state["overflow"]:
                try:
                    proc.kill()
                except OSError:
                    pass
                return

    def _close_pipes():
        # Deterministic teardown: refcount timing otherwise leaves these to
        # the cyclic collector, which is exactly the unclosed-file warning.
        for pipe in buffers:
            try:
                pipe.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=_drain, args=(pipe,), daemon=True)
        for pipe in buffers
    ]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        remaining = deadline - time.monotonic()
        thread.join(max(0.0, remaining))
    if any(thread.is_alive() for thread in threads):
        try:
            proc.kill()
        except OSError:
            pass
        for thread in threads:
            thread.join(timeout=5)
        try:
            proc.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        outcome = subprocess.TimeoutExpired(
            argv,
            timeout,
            output="".join(buffers[proc.stdout]),
            stderr="".join(buffers[proc.stderr]),
        )
        _close_pipes()
        raise outcome
    try:
        proc.wait(timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    for thread in threads:
        thread.join(timeout=5)
    outcome = None
    if state["overflow"]:
        outcome = OutputTooLarge(argv)
    elif proc.returncode is None:
        # Pipes are at EOF yet nothing reaped: wedged past every grace, so
        # report it as a timeout rather than a result with no exit status.
        outcome = subprocess.TimeoutExpired(
            argv,
            timeout,
            output="".join(buffers[proc.stdout]),
            stderr="".join(buffers[proc.stderr]),
        )
    _close_pipes()
    if outcome is not None:
        raise outcome
    return subprocess.CompletedProcess(
        argv,
        proc.returncode,
        "".join(buffers[proc.stdout]),
        "".join(buffers[proc.stderr]),
    )
