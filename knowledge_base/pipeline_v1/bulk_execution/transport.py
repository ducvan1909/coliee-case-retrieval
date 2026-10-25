from __future__ import annotations
import json
import time
from urllib import request as urlrequest
from urllib.error import HTTPError,URLError
from ..au_compact.jobs_client import payload_digest


def group_id(mode,jobs):
    return payload_digest({"mode":mode,"jobs":jobs})


class GroupTransportError(ValueError):
    def __init__(self,kind,*,outcome_unknown=False,http_status=None):
        self.kind=kind;self.outcome_unknown=outcome_unknown;self.http_status=http_status
        super().__init__(kind)


class GroupTransport:
    """POST once or recover by group identity; never POST a changed payload."""
    def __init__(self,cfg,opener=urlrequest.urlopen,clock=time.monotonic,sleep=time.sleep):
        self.cfg=cfg;self.opener=opener;self.clock=clock;self.sleep=sleep
        self.base=cfg['url'].removesuffix('/v1/chat/completions')
        self.stats={'http_requests':0,'post_attempts':0,'get_attempts':0,'sent_bytes':0,'received_bytes':0,'http_wall_seconds':0,'events':[]}

    def _http(self,method,route,value=None,*,remaining=None):
        encoded=None if value is None else json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        if encoded is not None and len(encoded)>16*1024*1024:raise GroupTransportError('group_body_too_large')
        self.stats['http_requests']+=1
        self.stats['post_attempts' if method=='POST' else 'get_attempts']+=1
        self.stats['sent_bytes']+=len(encoded or b'')
        req=urlrequest.Request(self.base+route,data=encoded,headers={'Authorization':'Bearer '+self.cfg['token'],'Content-Type':'application/json'},method=method)
        started=self.clock()
        try:
            timeout=min(self.cfg.get('timeout',60),remaining if remaining is not None else self.cfg.get('timeout',60))
            with self.opener(req,timeout=max(.001,timeout)) as response:
                raw=response.read(16*1024*1024+1)
            self.stats['received_bytes']+=len(raw)
            if len(raw)>16*1024*1024:raise GroupTransportError('group_response_too_large')
            body=json.loads(raw)
            if not isinstance(body,dict):raise GroupTransportError('group_invalid_envelope')
            return body
        except HTTPError as exc:
            code=exc.code;exc.close();self.stats['events'].append({'method':method,'http_status':code})
            raise GroupTransportError('group_http',outcome_unknown=method=='POST' and code>=500,http_status=code) from None
        except (URLError,TimeoutError,OSError):
            self.stats['events'].append({'method':method,'kind':'transport'})
            raise GroupTransportError('group_transport',outcome_unknown=method=='POST') from None
        except (ValueError,UnicodeError) as exc:
            if isinstance(exc,GroupTransportError):raise
            raise GroupTransportError('group_invalid_json',outcome_unknown=method=='POST') from None
        finally:self.stats['http_wall_seconds']+=self.clock()-started

    def admit(self,mode,jobs,*,resume=False):
        gid=group_id(mode,jobs)
        route='/v1/batches' if mode=='bulk' else '/v1/corpora'
        if resume:
            try:return self.progress(mode,gid,0),True
            except GroupTransportError as exc:
                if exc.http_status!=404:raise
        key='batch_id' if mode=='bulk' else 'corpus_id'
        try:return self._http('POST',route,{key:gid,'jobs':jobs}),False
        except GroupTransportError as exc:
            if not exc.outcome_unknown:raise
            # Lost acknowledgement does not authorize another inference attempt.
            try:return self.progress(mode,gid,0),True
            except GroupTransportError:
                raise GroupTransportError('group_ack_unknown',outcome_unknown=True) from None

    def progress(self,mode,gid,after,*,remaining=None):
        route='/v1/batches/' if mode=='bulk' else '/v1/corpora/'
        return self._http('GET',route+gid+f'?after={after}&limit=32',remaining=remaining)
