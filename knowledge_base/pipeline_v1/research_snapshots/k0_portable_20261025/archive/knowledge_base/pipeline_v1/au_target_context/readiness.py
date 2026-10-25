"""One bounded run warmup and sanitized host readiness diagnostics."""
from __future__ import annotations

import json
import math
import threading
from urllib import request
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit


class ReadinessDeadlineError(RuntimeError):
    """Resumable host readiness/retrieval deadline, never a token budget error."""


class ReadinessGate:
    def __init__(self, cfg, opener, clock, sleep, persist):
        self.cfg, self.opener = cfg, opener
        self.clock, self.sleep, self.persist = clock, sleep, persist
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.started = clock()
        self.limit = float(cfg.get('readiness_seconds', 600))
        self.worker_limit = float(cfg.get('retrieval_readiness_seconds', min(30, self.limit)))
        self.backoff = float(cfg.get('job_poll_seconds', 2))
        if not all(math.isfinite(v) and v > 0 for v in (self.limit, self.worker_limit, self.backoff)):
            raise ValueError('finite positive readiness bounds required')
        self.limit = min(600, self.limit)
        self.worker_limit = min(30, self.limit, self.worker_limit)
        parts = urlsplit(cfg['jobs_url'])
        self.health_url = urlunsplit((parts.scheme, parts.netloc, '/health', '', ''))
        self.report = {'status': 'not_needed', 'ready': None, 'http_status': None,
                       'error_class': None, 'count': 0, 'elapsed_ms': 0,
                       'warmup_count': 0, 'warmup_elapsed_ms': 0,
                       'deadline_seconds': self.limit,
                       'retrieval_deadline_seconds': self.worker_limit}

    def snapshot(self):
        with self.lock:
            return dict(self.report)

    def record(self, status, ready, error_class=None):
        with self.lock:
            if self.stopped.is_set():
                ready, error_class = False, 'ReadinessDeadlineError'
            self.report.update(http_status=status, ready=ready, error_class=error_class,
                               count=self.report['count'] + 1,
                               elapsed_ms=round((self.clock() - self.started) * 1000, 3))
            self.persist(self.snapshot())

    def check(self):
        if self.stopped.is_set():
            raise ReadinessDeadlineError('shared readiness gate stopped dispatch')

    def stop(self):
        with self.lock:
            if self.stopped.is_set():
                return
            self.stopped.set()
            self.report['last_observation_error_class'] = self.report['error_class']
            self.report.update(status='deadline_exhausted', ready=False,
                               error_class='ReadinessDeadlineError',
                               elapsed_ms=round((self.clock() - self.started) * 1000, 3))
            self.persist(self.snapshot())

    def warmup(self, needed):
        if not needed:
            self.persist(self.snapshot())
            return
        self.started = self.clock()
        deadline = self.started + self.limit
        self.report['status'] = 'waiting'
        # Time and count bounds also terminate with injected nonadvancing clocks.
        for _ in range(601):
            remaining = deadline - self.clock()
            if remaining <= 0:
                break
            req = request.Request(self.health_url, method='GET', headers={
                'Authorization': 'Bearer ' + self.cfg['token']})
            status, ready, error = None, False, None
            try:
                with self.opener(req, timeout=min(float(self.cfg.get('timeout', 60)), remaining)) as response:
                    status = getattr(response, 'status', 200)
                    body = json.loads(response.read())
                ready = status == 200 and isinstance(body, dict) and body.get('ready') is True
                if not ready:
                    error = 'NotReady'
            except HTTPError as exc:
                status, error = exc.code, 'HTTPError'
                exc.close()
            except (ValueError, UnicodeError):
                error = 'InvalidHealthResponse'
            except TimeoutError:
                error = 'TimeoutError'
            except (URLError, OSError):
                error = 'TransportError'
            self.record(status, ready, error)
            self.report['warmup_count'] += 1
            self.report['warmup_elapsed_ms'] = round((self.clock() - self.started) * 1000, 3)
            if ready and self.clock() <= deadline:
                self.report['status'] = 'ready'
                self.persist(self.snapshot())
                return
            remaining = deadline - self.clock()
            if remaining <= 0:
                break
            self.sleep(min(self.backoff, remaining))
        self.stop()
