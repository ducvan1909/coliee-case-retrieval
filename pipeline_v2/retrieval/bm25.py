"""Versioned Unicode BM25 and unique-case rank fusion, no stopword removal."""
from collections import Counter
import math
import re


def analyze(text):
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


class BM25:
    def __init__(self, documents, k1=1.5, b=0.75):
        self.documents = list(documents)
        self.k1, self.b = k1, b
        self.terms = [Counter(analyze(d["text"])) for d in self.documents]
        self.lengths = [sum(t.values()) for t in self.terms]
        self.avg = sum(self.lengths)/len(self.lengths) if self.lengths else 1
        self.df = Counter(t for doc in self.terms for t in doc)

    def search(self, query, limit=20, exclude_case=None):
        result = []
        for d, terms, length in zip(self.documents, self.terms, self.lengths):
            if d["case_id"] == exclude_case:
                continue
            score = 0.0
            for term in set(analyze(query)):
                tf = terms[term]
                if tf:
                    idf = math.log(1+(len(self.documents)-self.df[term]+0.5)/(self.df[term]+0.5))
                    score += idf*tf*(self.k1+1)/(tf+self.k1*(1-self.b+self.b*length/(self.avg or 1)))
            if score > 0:
                result.append({**d, "score":score})
        return sorted(result, key=lambda x:(-x["score"], x.get("passage_id",x["case_id"])))[:limit]


def rank_cases(hits, limit=None):
    result, seen = [], set()
    for hit in hits:
        if hit["case_id"] not in seen:
            seen.add(hit["case_id"])
            result.append({**hit, "rank":len(result)+1})
    return result if limit is None else result[:limit]


def fuse_case_ranks(channels, limit=20, k=60):
    results = {}
    for channel, hits in channels.items():
        for hit in rank_cases(hits):
            case = hit["case_id"]
            row = results.setdefault(case, {"case_id":case,"score":0.0,"channels":{}})
            row["score"] += 1/(k+hit["rank"])
            row["channels"][channel] = {k:v for k,v in hit.items() if k != "text"}
    return sorted(results.values(),key=lambda r:(-r["score"],r["case_id"]))[:limit]
