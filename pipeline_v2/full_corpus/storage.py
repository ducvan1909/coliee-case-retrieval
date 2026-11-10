"""Read-only cache audit and paged Qdrant adapter; never load all vectors."""
import json
from pathlib import Path
import numpy as np
from ..retrieval.cache import Cache,validate_vectors
from ..retrieval.qdrant import QdrantStore,point_id
from .common import M3Error,file_digest

PAYLOAD=('case_id','passage_id','source_hash','exact_input_sha256','span_bytes','parent_handle','policy_hash','tokenizer_fingerprint')

class FullCache(Cache):
    def usage(self):
        row=self.db.execute('SELECT COUNT(*),COALESCE(SUM(requests),0),COALESCE(SUM(tokens),0),SUM(tokens IS NULL),COALESCE(SUM(elapsed),0),SUM(elapsed IS NULL) FROM attempts').fetchone()
        return {'attempts':row[0],'model_requests':row[1],'known_input_tokens':row[2],'unknown_token_attempts':row[3] or 0,
                'recorded_request_elapsed_seconds':row[4],'unknown_elapsed_attempts':row[5] or 0,
                'status_counts':dict(self.db.execute('SELECT status,COUNT(*) FROM attempts GROUP BY status')),
                'development_chat_tokens':None}

class ReadonlyCache:
    def __init__(self,run,fp,dimensions):self.run=Path(run);self.fp=fp;self.dimensions=dimensions
    def get_batch(self,ids,hashes):
        from ..source.core import canonical,digest
        base=self.run/'vectors'/digest(canonical([self.fp,ids]));meta=base.with_suffix('.json');array=base.with_suffix('.npz')
        if not meta.exists() and not array.exists():return None
        if not meta.exists() or not array.exists():raise M3Error('Uncommitted/orphan cache; run resume for explicit recovery')
        m=json.loads(meta.read_bytes())
        if m!={'fingerprint':self.fp,'ids':ids,'input_hashes':hashes,'array_sha256':file_digest(array)}:raise M3Error('Cache identity/content drift')
        with np.load(array,allow_pickle=False) as z:
            if z['ids'].tolist()!=ids or z['input_hashes'].tolist()!=hashes or str(z['fingerprint'])!=self.fp:raise M3Error('Cache embedded identity drift')
            return validate_vectors(z['vectors'],len(ids),self.dimensions).copy()

class FullQdrant(QdrantStore):
    def validate_existing(self,lexical):
        offset=None;seen_offsets=set()
        while True:
            body={'limit':256,'with_payload':True,'with_vector':False}
            if offset is not None:body['offset']=offset
            page=self._request('POST',self.path+'/points/scroll',body)
            rows=page['points'];ids=[r.get('payload',{}).get('passage_id') for r in rows]
            if any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise M3Error('Invalid existing full collection IDs')
            expected=lexical.get_many('passage',ids)
            for row,p in zip(rows,expected):
                payload=row.get('payload',{})
                if row['id']!=point_id(p['passage_id'],self.fp) or payload.get('embedding_fingerprint')!=self.fp or any(payload.get(k)!=p[k] for k in PAYLOAD):raise M3Error('Foreign ID/payload in full collection')
            nxt=page.get('next_page_offset')
            if nxt is None:return
            if str(nxt) in seen_offsets:raise M3Error('Non-advancing DB pagination')
            seen_offsets.add(str(nxt))
            offset=nxt
    def ensure(self):
        info=self.info()
        if info is None:
            self._request('PUT',self.path,{'vectors':{'size':self.dim,'distance':'Cosine','on_disk':True}})
            for field in ('case_id','passage_id','embedding_fingerprint'):
                self._request('PUT',self.path+'/index?wait=true',{'field_name':field,'field_schema':'keyword'})
        else:
            self.check_schema(info)
            offset=None;seen_offsets=set()
            while True:
                body={'limit':256,'with_payload':True,'with_vector':False}
                if offset is not None:body['offset']=offset
                page=self._request('POST',self.path+'/points/scroll',body)
                if any(row.get('payload',{}).get('embedding_fingerprint')!=self.fp for row in page['points']):raise M3Error('Foreign fingerprint in full collection')
                next_offset=page.get('next_page_offset')
                if next_offset is None:break
                if str(next_offset) in seen_offsets:raise M3Error('Qdrant pagination did not advance')
                seen_offsets.add(str(next_offset))
                offset=next_offset
        return self.info()
    def check_schema(self,info=None):
        info=info or self.info()
        if info is None:raise M3Error('Full collection is missing')
        vectors=info['config']['params']['vectors']
        if vectors.get('size')!=self.dim or vectors.get('distance')!='Cosine' or vectors.get('on_disk') is not True:raise M3Error('Full DB vector schema differs')
    def count(self):return self._request('POST',self.path+'/points/count',{'exact':True})['count']
    def matches(self,passages,vectors):
        ids=[point_id(p['passage_id'],self.fp) for p in passages]
        rows=self._request('POST',self.path+'/points',{'ids':ids,'with_payload':True,'with_vector':True})
        byid={r['id']:r for r in rows}
        if len(byid)!=len(rows) or not set(byid).issubset(ids):raise M3Error('Duplicate/unrequested Qdrant IDs')
        for p,v in zip(passages,vectors):
            if point_id(p['passage_id'],self.fp) not in byid:continue
            row=byid[point_id(p['passage_id'],self.fp)];payload=row.get('payload',{})
            if payload.get('embedding_fingerprint')!=self.fp or any(payload.get(k)!=p[k] for k in PAYLOAD):raise M3Error('Stored full payload drift')
            stored=validate_vectors([row.get('vector')],1,self.dim)[0]
            if not np.allclose(stored,v,atol=1e-5,rtol=1e-5):raise M3Error('Stored full vector differs from committed cache')
        return len(rows)==len(ids)
