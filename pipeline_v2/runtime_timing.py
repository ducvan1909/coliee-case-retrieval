"""Opt-in hierarchical wall-time measurements for a single worker."""
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from math import ceil
from statistics import median
from time import perf_counter_ns


_current = ContextVar('runtime_timing', default=None)


@contextmanager
def measure(part):
    state = _current.get()
    if state is None:
        yield
        return
    started = perf_counter_ns()
    frame = [0]
    state['stack'].append(frame)
    try:
        yield
    finally:
        elapsed = perf_counter_ns() - started
        state['stack'].pop()
        if state['stack']:
            state['stack'][-1][0] += elapsed
        row = state['parts'][part]
        row[0] += 1
        row[1] += elapsed
        row[2] += elapsed - frame[0]


def timed(part):
    def decorate(method):
        @wraps(method)
        def wrapper(*args, **kwargs):
            if _current.get() is None:
                return method(*args, **kwargs)
            with measure(part):
                return method(*args, **kwargs)
        return wrapper
    return decorate


class TimingProfile:
    def __init__(self, enabled, trace):
        self.enabled = enabled
        self.trace = trace
        self.samples = defaultdict(list)

    @contextmanager
    def record(self, scope, **metadata):
        if not self.enabled:
            yield metadata
            return
        state = {'parts': defaultdict(lambda: [0, 0, 0]), 'stack': []}
        token = _current.set(state)
        started = perf_counter_ns()
        status = 'success'
        try:
            yield metadata
        except BaseException:
            status = 'error'
            raise
        finally:
            elapsed = perf_counter_ns() - started
            _current.reset(token)
            unmeasured = elapsed - sum(row[2] for row in state['parts'].values())
            state['parts']['unmeasured'] = [1, unmeasured, unmeasured]
            parts = {}
            for part, (count, inclusive, exclusive) in sorted(state['parts'].items()):
                self.samples[scope, part].append((count, exclusive, metadata.get('request_id')))
                parts[part] = {'calls': count, 'elapsed_ms': round(inclusive / 1e6, 3),
                               'exclusive_ms': round(exclusive / 1e6, 3)}
            self.samples[scope, 'total'].append((1, elapsed, metadata.get('request_id')))
            self.trace.emit('timing_breakdown', scope=scope, status=status,
                            elapsed_ms=round(elapsed / 1e6, 3), parts=parts, **metadata)

    def summary(self):
        result = {}
        for (scope, part), values in sorted(self.samples.items()):
            durations = sorted(row[1] for row in values)
            slowest = max(values, key=lambda row: row[1])
            result.setdefault(scope, {})[part] = {
                'calls': sum(row[0] for row in values), 'samples': len(values),
                'total_ms': round(sum(durations) / 1e6, 3),
                'p50_ms': round(median(durations) / 1e6, 3),
                'p95_ms': round(durations[ceil(len(durations) * .95) - 1] / 1e6, 3),
                'max_ms': round(slowest[1] / 1e6, 3), 'slowest_request_id': slowest[2],
            }
        return result
