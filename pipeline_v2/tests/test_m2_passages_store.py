import json
from pathlib import Path
import shutil
import unittest

from pipeline_v2.passages import PassageReader, PassageError, build_bundle, validate_bundle
from pipeline_v2.source import M1Error
from pipeline_v2.navigation import M2Error
from pipeline_v2.tests import test_m2_navigation_store as nav_tests
from pipeline_v2.tests.test_m2_navigation_store import REPO, reseal, read_json, write_json


class PassageStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        nav_tests.M2NavigationStoreTests.setUpClass()
        cls.root=nav_tests.M2NavigationStoreTests.root
        cls.bundle="pipeline_v2/artifacts/passages-fixture"
        configs=cls.root/"pipeline_v2/configs"
        for name in ("m2_passages.json","qwen3_embedding_4b_tokenizer.lock.json"):
            shutil.copyfile(REPO/"pipeline_v2/configs"/name,configs/name)
        lock=read_json(configs/"qwen3_embedding_4b_tokenizer.lock.json")
        shutil.copytree(REPO/lock["assets_dir"],cls.root/lock["assets_dir"])
        build_bundle(cls.root,"pipeline_v2/artifacts/m2-fixture",cls.bundle)

    @classmethod
    def tearDownClass(cls):
        nav_tests.M2NavigationStoreTests.tearDownClass()

    def test_validate_determinism_and_write_once(self):
        self.assertTrue(validate_bundle(self.root,self.bundle)["valid"])
        with self.assertRaises(PassageError):
            build_bundle(self.root,"pipeline_v2/artifacts/m2-fixture",self.bundle)
        other="pipeline_v2/artifacts/passages-second"
        build_bundle(self.root,"pipeline_v2/artifacts/m2-fixture",other)
        a=self.root/self.bundle; b=self.root/other
        self.assertEqual({p.relative_to(a).as_posix():p.read_bytes() for p in a.rglob('*') if p.is_file()},
                         {p.relative_to(b).as_posix():p.read_bytes() for p in b.rglob('*') if p.is_file()})

    def test_pagination_open_parent_and_source_order_neighbors(self):
        reader=PassageReader(self.root,self.bundle)
        page=reader.inspect("000001.txt",0,1)
        self.assertIsNotNone(page["next_offset"])
        p=page["items"][0]
        opened=reader.open_context("000001.txt",p["passage_id"])
        raw=nav_tests.M2NavigationStoreTests.raw_by_id["000001.txt"]
        self.assertEqual(opened["text"],raw[slice(*opened["span_bytes"])].decode())
        self.assertEqual(opened["hit_text"],p["text"])
        self.assertTrue(opened["diagnostic_only"])
        self.assertFalse(opened["M4_delivery_recorded"])
        with self.assertRaises(PassageError):reader.inspect("000001.txt",True,1)
        with self.assertRaises(PassageError):reader.open_context("000001.txt","wrong")

    def test_resealed_passage_tamper_rejected(self):
        target=self.root/"pipeline_v2/artifacts/passages-tamper"
        shutil.copytree(self.root/self.bundle,target)
        source=target/"sources/000001.json"
        payload=read_json(source); payload["passages"][0]["full_input_tokens"]+=1
        write_json(source,payload); reseal(target,"sources/000001.json")
        with self.assertRaises(PassageError):PassageReader(self.root,target).inspect("000001.txt")

    def test_same_instance_raw_profile_and_tokenizer_drift_rejected(self):
        reader=PassageReader(self.root,self.bundle)
        paths=[self.root/"data/task1_train_files_2026/cases/000001.txt",
               self.root/"pipeline_v2/configs/m2_passages.json",
               self.root/"pipeline_v2/configs/m2.json",
               self.root/"pipeline_v2/configs/m1.json"]
        lock=read_json(self.root/"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
        paths.append(self.root/lock["assets_dir"]/"tokenizer_config.json")
        for path in paths:
            old=path.read_bytes()
            try:
                path.write_bytes(old+b" ")
                with self.assertRaises((PassageError,M1Error,M2Error)):
                    reader.inspect("000001.txt")
            finally:path.write_bytes(old)


if __name__=="__main__":unittest.main()
