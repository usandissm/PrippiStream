"""Bounded daemon workers for cancellable, best-effort background metadata."""
import queue
import threading


def map_background(function, values, workers=2, cancelled=lambda: False):
    """Return (completed results in input order, complete).

Unlike ThreadPoolExecutor, these threads do not register an interpreter-exit
join. Cancellation stops queued work and returns promptly; an in-flight socket
must still have its own timeout. Never use for downloads or durable writes.
"""
    values = list(values)
    jobs, results = queue.Queue(), queue.Queue()
    for index, value in enumerate(values):
        jobs.put((index, value))
    stop = threading.Event()

    def worker():
        while not stop.is_set() and not cancelled():
            try:
                index, value = jobs.get_nowait()
            except queue.Empty:
                return
            try:
                result = function(value)
                results.put((index, result, None))
            except Exception as exc:
                results.put((index, None, exc))

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(min(max(1, workers), len(values)))]
    for thread in threads:
        thread.start()
    completed = {}
    try:
        while len(completed) < len(values) and not cancelled():
            try:
                index, result, error = results.get(timeout=0.05)
                if error is not None:
                    raise error
                completed[index] = result
            except queue.Empty:
                if not any(thread.is_alive() for thread in threads) and results.empty():
                    break
    finally:
        stop.set()
    return [completed[index] for index in sorted(completed)], len(completed) == len(values)
