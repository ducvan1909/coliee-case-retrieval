import unittest
from unittest.mock import Mock

import numpy as np
import requests

from pipeline_v2.retrieval.common import M3Error
from pipeline_v2.retrieval.qdrant import QdrantStore, point_id


class Response:
    def __init__(self,status=200,value=None,content=b""):
        self.status_code=status
        self.value=value or {"status":"ok","result":{}}
        self.content=content
    def raise_for_status(self):
        if self.status_code>=400:
            raise requests.HTTPError(str(self.status_code))
    def json(self): return self.value


class M3QdrantTests(unittest.TestCase):
    def setUp(self):
        self.session=Mock()
        self.store=QdrantStore("http://127.0.0.1:6333","pilot_test","fp",dimensions=3,session=self.session)
        self.passage={"case_id":"000001.txt","passage_id":"000001:abc","source_hash":"src",
                      "exact_input_sha256":"body","span_bytes":[10,25],"parent_handle":"p000003",
                      "policy_hash":"m2","tokenizer_fingerprint":"tok"}
        self.vector=np.array([[1.,0.,0.]],dtype=np.float32)

    def test_refuses_non_local_endpoint_and_unsafe_collection_name(self):
        for url,name in [("http://example.com:6333","pilot_test"),
                         ("http://127.0.0.1:6333","../collection")]:
            with self.subTest(url=url,name=name):
                with self.assertRaises(M3Error): QdrantStore(url,name,"fp",dimensions=3)

    def test_point_ids_are_stable_and_profile_scoped(self):
        a=point_id(self.passage["passage_id"],"fp")
        self.assertEqual(point_id(self.passage["passage_id"],"fp"),a)
        self.assertNotEqual(point_id(self.passage["passage_id"],"fp2"),a)

    def test_upsert_preserves_source_payload_and_refuses_truncated_batches(self):
        self.session.request.return_value=Response(value={"status":"ok","result":{"status":"completed"}})
        self.store.upsert([self.passage],self.vector)
        payload=self.session.request.call_args.kwargs["json"]["points"][0]
        self.assertEqual(payload["id"],point_id(self.passage["passage_id"],"fp"))
        self.assertEqual(payload["payload"]["passage_id"],self.passage["passage_id"])
        self.assertEqual(payload["payload"]["source_hash"],"src")
        self.assertEqual(payload["payload"]["span_bytes"],[10,25])
        with self.assertRaises(M3Error): self.store.upsert([self.passage,self.passage],self.vector)

    def test_search_filters_to_profile_and_excludes_active_query_case(self):
        self.session.request.return_value=Response(value={"status":"ok","result":{"points":[]}})
        self.store.search(self.vector[0],limit=5,exclude_case="000001.txt")
        body=self.session.request.call_args.kwargs["json"]
        self.assertEqual(body["filter"]["must"][0]["key"],"embedding_fingerprint")
        self.assertEqual(body["filter"]["must_not"][0]["key"],"case_id")
        self.assertEqual(body["filter"]["must_not"][0]["match"]["value"],"000001.txt")
        self.assertTrue(body["params"]["exact"])

    def test_verify_requires_exact_point_set_and_matching_payload(self):
        expected={"id":point_id(self.passage["passage_id"],"fp"),"payload":{**self.passage,"embedding_fingerprint":"fp"},"vector":[1.,0.,0.]}
        self.session.request.return_value=Response(value={"status":"ok","result":{"points":[expected],"next_page_offset":None}})
        self.assertEqual(self.store.verify([self.passage],self.vector)["points"],1)
        self.session.request.return_value=Response(value={"status":"ok","result":{"points":[]}})
        with self.assertRaises(M3Error): self.store.verify([self.passage],self.vector)

    def test_verify_rejects_extra_points_and_source_hash_drift(self):
        expected={"id":point_id(self.passage["passage_id"],"fp"),
                  "payload":{**self.passage,"embedding_fingerprint":"fp"},"vector":[1.,0.,0.]}
        extra={"id":point_id("000001:extra","fp"),"payload":{**self.passage,"passage_id":"000001:extra","embedding_fingerprint":"fp"},"vector":[1.,0.,0.]}
        self.session.request.return_value=Response(value={"status":"ok","result":{"points":[expected,extra],"next_page_offset":None}})
        with self.assertRaises(M3Error):self.store.verify([self.passage],self.vector)
        wrong={**expected,"payload":{**expected["payload"],"source_hash":"changed"}}
        self.session.request.return_value=Response(value={"status":"ok","result":{"points":[wrong],"next_page_offset":None}})
        with self.assertRaises(M3Error):self.store.verify([self.passage],self.vector)

    def test_verify_rejects_duplicate_expected_passage_ids(self):
        expected={"id":point_id(self.passage["passage_id"],"fp"),
                  "payload":{**self.passage,"embedding_fingerprint":"fp"},"vector":[1.,0.,0.]}
        self.session.request.return_value=Response(value={"status":"ok","result":{"points":[expected],"next_page_offset":None}})
        with self.assertRaisesRegex(M3Error, "Duplicate expected"):
            self.store.verify([self.passage,self.passage],np.tile(self.vector,(2,1)))

    def test_upsert_rejects_bad_vector_shape_and_nonfinite_values_before_http(self):
        for vectors in ([[1.,0.]], [[float("nan"),0.,1.]], [[2.,0.,0.]]) :
            with self.subTest(vectors=vectors):
                self.session.reset_mock()
                with self.assertRaises(M3Error): self.store.upsert([self.passage],vectors)
                self.session.request.assert_not_called()

    def test_ensure_refuses_existing_collection_with_wrong_vector_schema(self):
        bad={"status":"ok","result":{"config":{"params":{"vectors":{"size":4,"distance":"Cosine"}}}}}
        self.session.request.return_value=Response(value=bad)
        with self.assertRaises(M3Error): self.store.ensure()


if __name__=="__main__":
    unittest.main()
