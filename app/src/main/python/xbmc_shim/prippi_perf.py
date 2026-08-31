"""Fallback no-op per snapshot motore precedenti a platformcode.perf."""

import time

ENABLED = False


def refresh():
    return False


def mark(tag, t0=None):
    del tag, t0
    return time.time()


def note(tag, text=''):
    del tag, text

