"""Provide exclusive file locks for the existing runners on Windows and Unix."""
import errno
import os
import time

LOCK_EX, LOCK_NB, LOCK_UN = 2, 4, 8


def flock(handle, operation):
    if os.name != 'nt':
        import fcntl
        return fcntl.flock(handle, operation)
    import msvcrt
    descriptor = handle.fileno() if hasattr(handle, 'fileno') else handle
    position = os.lseek(descriptor, 0, os.SEEK_CUR)
    while True:
        try:
            os.lseek(descriptor, 0, os.SEEK_SET)
            mode = msvcrt.LK_UNLCK if operation & LOCK_UN else msvcrt.LK_NBLCK
            msvcrt.locking(descriptor, mode, 1)
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            if operation & LOCK_NB or operation & LOCK_UN:
                raise BlockingIOError(error.errno, 'File is locked by another process') from error
        finally:
            os.lseek(descriptor, position, os.SEEK_SET)
        time.sleep(.1)
