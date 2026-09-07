"""Linux-only exec launcher that kills the child when its parent disappears."""

import ctypes
import os
import signal
import sys

_PR_SET_PDEATHSIG = 1


def main(argv):
    expected_parent = int(argv[0])
    command = argv[1:]
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    if os.getppid() != expected_parent:
        os.kill(os.getpid(), signal.SIGKILL)
    os.execv(command[0], command)


if __name__ == "__main__":
    main(sys.argv[1:])
