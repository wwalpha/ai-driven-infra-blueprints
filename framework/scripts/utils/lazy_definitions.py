"""Single-flight loading with caller-owned lifetime, cache and lock."""
from concurrent.futures import Future


def load_once(lock, cache, key, load):
    with lock:
        future = cache.get(key)
        first = future is None
        if first:
            future = cache[key] = Future()
    if first:
        try:
            result = load()
        except BaseException as error:
            future.set_exception(error)
            raise
        else:
            future.set_result(result)
    return future.result()
