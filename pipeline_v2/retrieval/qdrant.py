"""Small explicit REST adapter for a local Qdrant server, not embedded mode."""
import uuid
from urllib.parse import quote, urlparse

import numpy as np
import requests

from .common import M3Error
from .cache import validate_vectors


NAMESPACE = uuid.UUID("a8979bd6-50a2-41f3-87d2-e2744801d753")


def point_id(passage_id, fingerprint):
    return str(uuid.uuid5(NAMESPACE,fingerprint+":"+passage_id))


class QdrantStore:
    def __init__(self,url,collection,fingerprint,dimensions=2560,session=None,timeout=60):
        if urlparse(url).hostname not in ("127.0.0.1","localhost","::1"):
            raise M3Error("M3 pilot Qdrant must be local")
        if not collection or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in collection):
            raise M3Error("Unsafe collection name")
        self.url=url.rstrip("/"); self.collection=collection; self.fp=fingerprint; self.dim=dimensions
        self.session=session or requests.Session(); self.timeout=timeout
        self.path="/collections/"+quote(collection,safe="")

    def _request(self,method,path,body=None,allow404=False):
        response=self.session.request(method,self.url+path,json=body,timeout=self.timeout)
        if response.status_code==404 and allow404:return None
        response.raise_for_status()
        value=response.json()
        if value.get("status")!="ok":raise M3Error("Qdrant request did not return ok")
        return value.get("result")

    def info(self):
        return self._request("GET",self.path,allow404=True)

    def server_info(self):
        response=self.session.request("GET",self.url+"/",timeout=self.timeout)
        response.raise_for_status()
        result=response.json()
        if not isinstance(result.get("version"),str):raise M3Error("Qdrant server version unavailable")
        return {k:result.get(k) for k in ("title","version","commit")}

    def ensure(self):
        info=self.info()
        if info is None:
            self._request("PUT",self.path,{"vectors":{"size":self.dim,"distance":"Cosine"}})
            for field in ("case_id","passage_id","embedding_fingerprint"):
                self._request("PUT",self.path+"/index?wait=true",{"field_name":field,"field_schema":"keyword"})
        else:
            vectors=info["config"]["params"]["vectors"]
            if vectors.get("size")!=self.dim or vectors.get("distance")!="Cosine":
                raise M3Error("Existing collection vector schema mismatch")
            rows=self.scroll()
            if any(p.get("payload",{}).get("embedding_fingerprint")!=self.fp for p in rows):
                raise M3Error("Existing collection belongs to another embedding profile")
        return self.info()

    def upsert(self,passages,vectors):
        vectors=validate_vectors(vectors,len(passages),self.dim)
        points=[]
        for p,v in zip(passages,vectors):
            payload={k:p[k] for k in ("case_id","passage_id","source_hash","exact_input_sha256","span_bytes","parent_handle","policy_hash","tokenizer_fingerprint")}
            payload["embedding_fingerprint"]=self.fp
            points.append({"id":point_id(p["passage_id"],self.fp),"vector":np.asarray(v,dtype=np.float32).tolist(),"payload":payload})
        if len(points)!=len(passages) or len(points)!=len(vectors):raise M3Error("Upsert batch size mismatch")
        return self._request("PUT",self.path+"/points?wait=true",{"points":points})

    def scroll(self):
        rows=[]; offset=None
        while True:
            body={"limit":256,"with_payload":True,"with_vector":True}
            if offset is not None:body["offset"]=offset
            response=self._request("POST",self.path+"/points/scroll",body)
            rows.extend(response["points"])
            offset=response.get("next_page_offset")
            if offset is None:return rows

    def verify(self,passages,vectors=None):
        rows=self.scroll(); byid={p["id"]:p for p in rows}
        expected={point_id(p["passage_id"],self.fp):p for p in passages}
        if len(expected)!=len(passages):raise M3Error("Duplicate expected Qdrant passage IDs")
        if len(byid)!=len(rows) or set(byid)!=set(expected):raise M3Error("Qdrant membership differs from pilot manifest")
        for i,p in enumerate(passages):
            row=byid[point_id(p["passage_id"],self.fp)]; payload=row.get("payload",{})
            if payload.get("embedding_fingerprint")!=self.fp or any(payload.get(k)!=p[k] for k in ("case_id","passage_id","source_hash","exact_input_sha256","span_bytes","parent_handle","policy_hash","tokenizer_fingerprint")):
                raise M3Error("Qdrant payload/profile drift")
            v=np.asarray(row.get("vector"),dtype=np.float32)
            if v.shape!=(self.dim,) or not np.isfinite(v).all() or not np.isclose(np.linalg.norm(v),1,atol=.002):
                raise M3Error("Invalid stored Qdrant vector")
            if vectors is not None and not np.allclose(v,vectors[i],atol=1e-5,rtol=1e-5):
                raise M3Error("Qdrant stored vector differs from exported cache")
        return {"status":"PASS","points":len(rows),"collection":self.collection}

    def search(self,vector,limit=20,exclude_case=None):
        vector=validate_vectors([vector],1,self.dim)[0]
        if type(limit) is not int or limit<1:raise M3Error("Invalid search limit")
        condition={"must":[{"key":"embedding_fingerprint","match":{"value":self.fp}}]}
        if exclude_case:condition["must_not"]=[{"key":"case_id","match":{"value":exclude_case}}]
        result=self._request("POST",self.path+"/points/query",{"query":np.asarray(vector,dtype=np.float32).tolist(),"limit":limit,"filter":condition,"with_payload":True,"params":{"exact":True}})
        return [{**p["payload"],"score":p["score"]} for p in result["points"]]

    def snapshot(self):
        return self._request("POST",self.path+"/snapshots?wait=true")

    def restore_test(self):
        snap=self.snapshot()
        response=self.session.request("GET",self.url+self.path+"/snapshots/"+quote(snap["name"],safe=""),timeout=self.timeout)
        response.raise_for_status()
        other=QdrantStore(self.url,self.collection+"_restore",self.fp,self.dim,self.session,self.timeout)
        if other.info() is not None:raise M3Error("Restore-test collection already exists; refuse overwrite")
        uploaded=self.session.post(self.url+other.path+"/snapshots/upload?priority=snapshot&wait=true",files={"snapshot":(snap["name"],response.content,"application/octet-stream")},timeout=self.timeout)
        uploaded.raise_for_status()
        if uploaded.json().get("status")!="ok":raise M3Error("Snapshot restore failed")
        return other,{"snapshot":snap["name"],"snapshot_bytes":len(response.content),"restored_collection":other.collection}
