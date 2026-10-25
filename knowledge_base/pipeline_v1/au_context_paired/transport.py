"""Paired-only opener overlay; no payload, prompt or baseline transport changes."""
from __future__ import annotations

import io
import json
import time
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class PairedTransport:
    """Retrieve first; one durable recovery permit per job, including unknown ACK."""

    def __init__(self, cfg, accounting, *, clock=time.monotonic, sleep=time.sleep,
                 readiness_seconds=600, backoff_seconds=None):
        self.cfg, self.accounting = cfg, accounting
        self.clock, self.sleep = clock, sleep
        self.limit = min(600, float(readiness_seconds))
        self.backoff = float(backoff_seconds or cfg.get("job_poll_seconds", 2))
        if self.limit <= 0 or self.backoff <= 0:
            raise ValueError("positive readiness/backoff bounds required")
        self.base = cfg["jobs_url"].rstrip("/")
        parts = urlsplit(self.base)
        self.health_url = urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))
        self.ready = False
        self.posts = {}
        self.proofs = {}
        self.observed = set()

    def _request(self, url):
        return urlrequest.Request(url, headers={"Authorization": "Bearer " + self.cfg["token"],
                                               "Content-Type": "application/json"}, method="GET")

    def _pause(self, deadline):
        remaining = deadline - self.clock()
        if remaining <= 0:
            self.accounting.block("paired readiness/retrieval deadline exhausted")
        self.sleep(min(self.backoff, remaining))

    def _get(self, req, deadline, kwargs):
        remaining = deadline - self.clock()
        if remaining <= 0:
            self.accounting.block("paired readiness/retrieval deadline exhausted")
        options = {**kwargs, "timeout": max(.001, min(float(kwargs.get("timeout", 60)), remaining))}
        try:
            with self.accounting(req, **options) as response:
                raw = response.read()
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                body = None
            return 200, body, raw
        except HTTPError as exc:
            raw = exc.read()
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeError):
                body = None
            return exc.code, body, raw
        except (URLError, TimeoutError, OSError):
            return None, None, b""

    def ensure_ready(self, deadline=None, **kwargs):
        deadline = self.clock() + self.limit if deadline is None else deadline
        while True:
            status, body, _ = self._get(self._request(self.health_url), deadline, kwargs)
            if status == 200 and isinstance(body, dict) and body.get("ready") is True:
                self.ready = True
                return {"url": self.health_url, "http_status": status, "ready": True,
                        "observed_at_unix": time.time()}
            self.ready = False
            self._pause(deadline)

    def __call__(self, req, **kwargs):
        if req.full_url != self.base and not req.full_url.startswith(self.base + "/"):
            return self.accounting(req, **kwargs)
        if req.get_method() == "POST":
            job = json.loads(req.data)["job_id"]
            proof = self.proofs.pop(job, None)
            if not proof:
                self.accounting.block("paired POST requires fresh authoritative absence evidence")
            if job in self.observed:
                self.accounting.block("observed existing job must never be resubmitted")
            self.posts[job] = req
            self.accounting.recovery_proof = proof
            return self.accounting(req, **kwargs)
        if req.get_method() != "GET":
            return self.accounting(req, **kwargs)
        job = req.full_url.removeprefix(self.base + "/")
        deadline = self.clock() + self.limit
        if not self.ready:
            self.ensure_ready(deadline, **kwargs)
        absent = []
        while True:
            # Each absence observation must be paired with fresh readiness.
            health = self.ensure_ready(deadline, **kwargs)
            status, body, raw = self._get(req, deadline, kwargs)
            if status == 200 and isinstance(body, dict):
                self.proofs.pop(job, None)
                self.observed.add(job)
                return Response(raw)
            if status == 404 and body == {"detail": "Unknown job"}:
                recovery = self.accounting.ledger.get("job_recovery", {}).get(job, {})
                prior = [a for a in self.accounting.ledger["attempts"] if a.get("job_id") == job]
                if recovery.get("retry_used") or len(prior) >= 2:
                    self.accounting.block("paired recovery retry already used; job remains absent")
                if job in self.observed:
                    self.accounting.block("previously observed job disappeared; explicit review required")
                absent.append({"job_url": req.full_url, "http_status": 404,
                               "detail": "Unknown job", "health": health,
                               "observed_at_unix": time.time(), "observed_monotonic": self.clock()})
                if len(absent) >= 2:
                    proof = {"job_id": job, "gateway_url": self.base, "observations": absent[-2:],
                             "backoff_seconds": self.backoff}
                    self.proofs[job] = proof
                    if job in self.posts:
                        # jobs_client polls after uncertain POST; return the retry ACK.
                        return self(self.posts[job], **kwargs)
                    raise HTTPError(req.full_url, 404, "Unknown job", {}, Response(raw))
            else:
                absent = []
                self.ready = False
            self._pause(deadline)
