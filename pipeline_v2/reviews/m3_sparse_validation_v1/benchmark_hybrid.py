"""Run the fixed three-query hybrid workload with sparse lexical arrays."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path

from pipeline_v2.reviews.m3_hybrid_validation_v1 import benchmark_cached
from pipeline_v2.sparse_bm25.index import SparseHybridSession


class MemoryCounters(ctypes.Structure):
    _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            'peak_working_set', 'working_set', 'peak_paged_pool', 'paged_pool',
            'peak_nonpaged_pool', 'nonpaged_pool', 'pagefile', 'peak_pagefile', 'private_usage')]


def memory_snapshot():
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    if not get_info(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return {name: int(getattr(counters, name)) for name in (
        'peak_working_set', 'working_set', 'private_usage')}


class MeasuredSparseHybridSession(SparseHybridSession):
    def __init__(self, root):
        before = memory_snapshot()
        super().__init__(root)
        self.memory_rows = [{'phase': 'before_session', **before},
                            {'phase': 'session_opened', **memory_snapshot()}]
        self._record_memory()

    def _record_memory(self):
        output = Path(__file__).resolve().parent / 'hybrid_memory.json'
        output.write_text(json.dumps(self.memory_rows, indent=2), encoding='utf-8')

    def search_cached(self, *args, **kwargs):
        result = super().search_cached(*args, **kwargs)
        self.memory_rows.append({'phase': 'query_complete', 'query_case': result['query_case'],
                                 **memory_snapshot()})
        self._record_memory()
        return result


def main():
    # Reuse the same workload, independent RRF check and evidence format.
    benchmark_cached.HybridSession = MeasuredSparseHybridSession
    benchmark_cached.main()


if __name__ == '__main__':
    main()
