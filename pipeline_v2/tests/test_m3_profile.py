import json
from pathlib import Path
import shutil
import tempfile
import unittest

from pipeline_v2.retrieval.common import M3Error, load_profile


REPO = Path(__file__).resolve().parents[2]
ACCEPTED_SEAL = "0ed42d51023adaf47c1205fa925f18f31b7aacb58b0c8e44c7d23288d123dda6"
ACCEPTED_BUNDLE = "pipeline_v2/artifacts/m2_passages_20261106_v1"


class M3ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        configs = self.tmp / "pipeline_v2/configs"
        configs.mkdir(parents=True)
        for name in ("m3.json", "m3_user_selection.json"):
            shutil.copyfile(REPO / "pipeline_v2/configs" / name, configs / name)

    def read_profile(self):
        path = self.tmp / "pipeline_v2/configs/m3.json"
        return json.loads(path.read_bytes())

    def write_profile(self, profile):
        (self.tmp / "pipeline_v2/configs/m3.json").write_text(json.dumps(profile))

    def test_accepted_bundle_and_seal_are_pinned_before_plan_creation(self):
        profile = load_profile(self.tmp)
        self.assertEqual(profile["passages_bundle"], ACCEPTED_BUNDLE)
        self.assertEqual(profile["accepted_m2_seal_sha256"], ACCEPTED_SEAL)
        for field, value in (("passages_bundle", "pipeline_v2/artifacts/another_bundle"),
                             ("accepted_m2_seal_sha256", "0" * 64)):
            with self.subTest(field=field):
                changed = self.read_profile()
                changed[field] = value
                self.write_profile(changed)
                with self.assertRaises(M3Error):
                    load_profile(self.tmp)


if __name__ == "__main__":
    unittest.main()
