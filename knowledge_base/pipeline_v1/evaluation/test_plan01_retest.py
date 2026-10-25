from __future__ import annotations

import copy
import json
import unittest

from knowledge_base.pipeline_v1.scripts.validate_plan01 import (
    PIPELINE_DIR,
    validate_split_registry,
)


class Plan01RetestFaultInjection(unittest.TestCase):
    def test_non_string_case_id_is_reported_without_validator_crash(self):
        registry = json.loads(
            (PIPELINE_DIR / "manifests/split_registry.v1.json").read_text(
                encoding="utf-8"
            )
        )
        broken = copy.deepcopy(registry)
        broken["pilot"]["train"]["short"]["development"][0] = 123

        try:
            errors, details = validate_split_registry(broken)
        except Exception as exc:  # Contract validator must produce a FAIL report.
            self.fail(f"validator crashed instead of rejecting malformed input: {exc!r}")

        self.assertTrue(any("malformed case IDs" in error for error in errors))
        self.assertEqual(details["status"], "fail")


if __name__ == "__main__":
    unittest.main()
