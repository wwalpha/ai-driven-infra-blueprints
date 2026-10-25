"""Single-flight loading with caller-owned lifetime, cache and lock."""

from concurrent.futures import Future


def load_once(
    lock, cache, key, load, *, evict_on_failure: bool = False, lookup_locked=None
):
    """lookup_locked returns (found, value) under the caller's lock, before cache access."""
    with lock:
        if lookup_locked is not None:
            found, value = lookup_locked()
            if found:
                return value
        future = cache.get(key)
        first = future is None
        if first:
            future = cache[key] = Future()
    if first:
        try:
            result = load()
        except BaseException as error:
            future.set_exception(error)
            if evict_on_failure:
                with lock:
                    if cache.get(key) is future:
                        del cache[key]
            raise
        else:
            future.set_result(result)
    return future.result()
