"""Atomic vector batches plus transactional attempt ledger. No pickled arrays."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from contextlib import contextmanager

import numpy as np

from ..source.core import canonical, digest
from .common import M3Error, write_json


def validate_vectors(vectors, count, dimensions):
    a = np.asarray(vectors, dtype=np.float32)
    if a.shape != (count,dimensions) or not np.isfinite(a).all():
        raise M3Error("Invalid vector shape/nonfinite values")
    if count and not np.allclose(np.linalg.norm(a,axis=1),1,atol=2e-3,rtol=0):
        raise M3Error("Vectors must be L2-normalized")
    return a


class Cache:
    def __init__(self, run_dir, fingerprint, dimensions=2560):
        self.run = Path(run_dir)
        self.run.mkdir(parents=True,exist_ok=True)
        self.fp, self.dimensions = fingerprint, dimensions
        self.db = sqlite3.connect(self.run/"ledger.sqlite3")
        self.db.execute("CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, batch TEXT, phase TEXT, started REAL, elapsed REAL, status TEXT, requests INTEGER, tokens INTEGER, error TEXT)")
        if "receipt" not in {r[1] for r in self.db.execute("PRAGMA table_info(attempts)")}:
            self.db.execute("ALTER TABLE attempts ADD COLUMN receipt TEXT")
        self.db.commit()

    def begin(self,batch,phase,tokens=None):
        with self.db:
            cur=self.db.execute("INSERT INTO attempts(batch,phase,started,status,requests,tokens) VALUES(?,?,?,'started',1,?)",(batch,phase,time.time(),tokens))
        return cur.lastrowid

    def finish(self, ident, status, elapsed, tokens=None, error=None, receipt=None):
        with self.db:
            self.db.execute("UPDATE attempts SET status=?, elapsed=?, tokens=?, error=?,receipt=? WHERE id=?",(status,elapsed,tokens,error,json.dumps(receipt) if receipt is not None else None,ident))

    def _base(self, ids):
        return self.run/"vectors"/digest(canonical([self.fp,ids]))

    def get_batch(self, ids, input_hashes):
        base=self._base(ids)
        meta_path, array_path=base.with_suffix(".json"),base.with_suffix(".npz")
        if not meta_path.exists():
            if array_path.exists():
                try:
                    with np.load(array_path,allow_pickle=False) as z:
                        if z["ids"].tolist()!=ids or z["input_hashes"].tolist()!=input_hashes or str(z["fingerprint"])!=self.fp:
                            raise M3Error("Orphan vector identity mismatch")
                        validate_vectors(z["vectors"],len(ids),self.dimensions)
                    write_json(meta_path,{"fingerprint":self.fp,"ids":ids,"input_hashes":input_hashes,"array_sha256":digest(array_path.read_bytes())},replace=True)
                    return self.get_batch(ids,input_hashes)
                except (KeyError,ValueError,OSError) as exc:
                    raise M3Error("Orphan vector shard cannot be safely recovered") from exc
            return None
        meta=json.loads(meta_path.read_bytes())
        if meta.get("fingerprint")!=self.fp or meta.get("ids")!=ids or meta.get("input_hashes")!=input_hashes:
            raise M3Error("Cache identity/profile drift")
        if not array_path.exists() or digest(array_path.read_bytes())!=meta["array_sha256"]:
            raise M3Error("Corrupt/missing committed vector cache")
        with np.load(array_path,allow_pickle=False) as z:
            if z["ids"].tolist()!=ids or z["input_hashes"].tolist()!=input_hashes or str(z["fingerprint"])!=self.fp:
                raise M3Error("Vector shard embedded identity mismatch")
            vectors=validate_vectors(z["vectors"],len(ids),self.dimensions)
        return vectors

    def commit_batch(self, ids, input_hashes, vectors):
        vectors=validate_vectors(vectors,len(ids),self.dimensions)
        old=self.get_batch(ids,input_hashes)
        if old is not None:
            if not np.array_equal(old,vectors):raise M3Error("Refuse to replace committed vectors")
            return
        base=self._base(ids);base.parent.mkdir(parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix=".vector-",dir=base.parent)
        try:
            with os.fdopen(fd,"wb") as stream:
                np.savez(stream,vectors=vectors,ids=np.asarray(ids,dtype=str),input_hashes=np.asarray(input_hashes,dtype=str),fingerprint=np.asarray(self.fp))
                stream.flush();os.fsync(stream.fileno())
            os.replace(name,base.with_suffix(".npz"))
        finally:
            if os.path.exists(name):os.unlink(name)
        write_json(base.with_suffix(".json"),{"fingerprint":self.fp,"ids":ids,"input_hashes":input_hashes,
                   "array_sha256":digest(base.with_suffix(".npz").read_bytes())},replace=True)

    def usage(self):
        rows=self.db.execute("SELECT id,batch,phase,started,elapsed,status,requests,tokens,error,receipt FROM attempts ORDER BY id").fetchall()
        names=["id","batch","phase","started","elapsed_seconds","status","requests","input_tokens","error","receipt"]
        attempts=[dict(zip(names,r)) for r in rows]
        for a in attempts:a["receipt"]=json.loads(a["receipt"]) if a["receipt"] else None
        return {"attempts":attempts,"model_requests":len(rows),
                "known_input_tokens":sum(r[7] or 0 for r in rows),
                "unknown_token_attempts":sum(r[7] is None for r in rows),"development_chat_tokens":None}


@contextmanager
def run_lock(run_dir):
    """OS-backed SQLite lock: process death releases it, no stale PID files."""
    path=Path(run_dir)/"run_lock.sqlite3"
    db=sqlite3.connect(path,timeout=0)
    try:
        try:
            db.execute("CREATE TABLE IF NOT EXISTS mutex(id INTEGER PRIMARY KEY)")
            db.commit()
            db.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:raise M3Error("Another M3 operation owns this run") from exc
        yield
    finally:
        db.rollback();db.close()
