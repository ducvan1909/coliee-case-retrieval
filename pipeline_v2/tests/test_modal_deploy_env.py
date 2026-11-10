import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from pipeline_v2 import deploy_modal
from pipeline_v2.source.core import canonical, digest


class ModalDeployEnvTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env_file = self.tmp / "fixture.env"
        self.token_id = "fixture-id-not-a-real-credential"
        self.token_secret = "fixture-secret-never-print"

    def write_env(self, body):
        self.env_file.write_bytes(body.encode("utf-8"))
        return self.env_file

    def test_parser_handles_bom_quotes_hash_comments_and_no_expansion(self):
        self.env_file.write_bytes(("\ufeffMODAL_TOKEN_ID=\"id#part\"\n"
                                   "MODAL_TOKEN_SECRET='secret#part'\n"
                                   "MODAL_PROFILE=qa # trailing comment\n"
                                   "MODAL_ENVIRONMENT=literal#hash\n").encode("utf-8"))
        parsed = deploy_modal.parse_env(self.env_file)
        self.assertEqual(parsed, {
            "MODAL_TOKEN_ID": "id#part",
            "MODAL_TOKEN_SECRET": "secret#part",
            "MODAL_PROFILE": "qa",
            "MODAL_ENVIRONMENT": "literal#hash",
        })
        no_expansion = self.write_env('MODAL_PROFILE="${HOME}-$MODAL_TOKEN_ID\\n"\n')
        self.assertEqual(deploy_modal.parse_env(no_expansion)["MODAL_PROFILE"], "${HOME}-$MODAL_TOKEN_ID\\n")

    def test_parser_rejects_duplicate_unknown_malformed_and_unclosed_values_without_leaking(self):
        malformed = [
            f"MODAL_TOKEN_SECRET={self.token_secret}\nMODAL_TOKEN_SECRET=second\n",
            f"UNKNOWN_SETTING={self.token_secret}\n",
            f"MODAL_PROFILE={self.token_secret} \"broken\n",
            f"MODAL_TOKEN_SECRET=\"{self.token_secret}\n",
            f"MODAL_PROFILE=\"{self.token_secret}\"unexpected\n",
            f"{self.token_secret}\n",
        ]
        for body in malformed:
            with self.subTest(body=body[:25]):
                path = self.write_env(body)
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    with self.assertRaises(deploy_modal.EnvConfigError) as caught:
                        deploy_modal.parse_env(path)
                self.assertNotIn(self.token_secret, str(caught.exception))
                self.assertNotIn(self.token_secret, stdout.getvalue() + stderr.getvalue())
                self.assertEqual(stdout.getvalue(), "")

    def test_file_values_override_nonblank_process_values_and_blank_values_fall_through(self):
        values = {
            "MODAL_TOKEN_ID": self.token_id,
            "MODAL_TOKEN_SECRET": self.token_secret,
            "MODAL_PROFILE": "file-profile",
            "MODAL_ENVIRONMENT": "",
        }
        parent = {
            "MODAL_TOKEN_ID": "parent-id",
            "MODAL_TOKEN_SECRET": "parent-secret",
            "MODAL_PROFILE": "parent-profile",
            "MODAL_ENVIRONMENT": "parent-environment",
            "UNRELATED_PARENT_SETTING": "keep-me",
        }
        env = deploy_modal.build_environment(values, parent)
        self.assertEqual(env["MODAL_TOKEN_ID"], self.token_id)
        self.assertEqual(env["MODAL_TOKEN_SECRET"], self.token_secret)
        self.assertEqual(env["MODAL_PROFILE"], "file-profile")
        self.assertEqual(env["MODAL_ENVIRONMENT"], "parent-environment")
        self.assertEqual(env["UNRELATED_PARENT_SETTING"], "keep-me")

    def test_blank_settings_preserve_sdk_profile_fallback_when_process_has_no_values(self):
        env = deploy_modal.build_environment({
            "MODAL_TOKEN_ID": "", "MODAL_TOKEN_SECRET": "",
            "MODAL_PROFILE": "", "MODAL_ENVIRONMENT": "",
        }, {"PATH": "fixture-path"})
        for key in deploy_modal.ALLOWED_KEYS:
            self.assertNotIn(key, env)
        self.assertEqual(env["PATH"], "fixture-path")

    def test_file_and_effective_token_pairs_must_each_be_complete(self):
        with self.assertRaises(deploy_modal.EnvConfigError):
            deploy_modal.build_environment({"MODAL_TOKEN_ID": self.token_id}, {
                "MODAL_TOKEN_SECRET": "parent-secret",
            })
        with self.assertRaises(deploy_modal.EnvConfigError):
            deploy_modal.build_environment({}, {"MODAL_TOKEN_ID": "parent-id"})
        complete = deploy_modal.build_environment({"MODAL_TOKEN_ID": "", "MODAL_TOKEN_SECRET": ""}, {
            "MODAL_TOKEN_ID": "parent-id", "MODAL_TOKEN_SECRET": "parent-secret",
        })
        self.assertEqual(complete["MODAL_TOKEN_ID"], "parent-id")
        self.assertEqual(complete["MODAL_TOKEN_SECRET"], "parent-secret")

    def test_local_check_is_read_only_sanitized_and_does_not_overwrite_env_file(self):
        root = self.tmp / "repo"
        config_dir = root / "pipeline_v2/configs"
        config_dir.mkdir(parents=True)
        shutil.copyfile(deploy_modal.ROOT / "pipeline_v2/configs/m3.json", config_dir / "m3.json")
        self.write_env(
            f'MODAL_TOKEN_ID="{self.token_id}"\n'
            f'MODAL_TOKEN_SECRET="{self.token_secret}"\n'
            'MODAL_PROFILE=fixture-profile\nMODAL_ENVIRONMENT=fixture-environment\n'
        )
        before = self.env_file.read_bytes()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            result = deploy_modal.check_configuration(root, self.env_file, parent_env={})
        self.assertEqual(result["status"], "local_configuration_only")
        self.assertFalse(result["authentication_verified"])
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["profile"], "fixture-profile")
        self.assertEqual(result["environment"], "fixture-environment")
        serialized = json.dumps(result)
        self.assertNotIn(self.token_id, serialized)
        self.assertNotIn(self.token_secret, serialized)
        self.assertNotIn(self.token_id, stdout.getvalue() + stderr.getvalue())
        self.assertNotIn(self.token_secret, stdout.getvalue() + stderr.getvalue())
        self.assertEqual(self.env_file.read_bytes(), before)
        self.assertFalse((root / "pipeline_v2/.env").exists())

    def test_check_redacts_credential_values_accidentally_used_as_profile_labels(self):
        root = self.tmp / "repo"
        config_dir = root / "pipeline_v2/configs"
        config_dir.mkdir(parents=True)
        shutil.copyfile(deploy_modal.ROOT / "pipeline_v2/configs/m3.json", config_dir / "m3.json")
        self.write_env(
            f'MODAL_TOKEN_ID="{self.token_id}"\n'
            f'MODAL_TOKEN_SECRET="{self.token_secret}"\n'
            f'MODAL_PROFILE="{self.token_secret}"\n'
            f'MODAL_ENVIRONMENT="prefix-{self.token_id}-suffix"\n'
        )
        result = deploy_modal.check_configuration(root, self.env_file, parent_env={})
        self.assertEqual(result["profile"], "[redacted]")
        self.assertEqual(result["environment"], "[redacted]")
        self.assertNotIn(self.token_id, json.dumps(result))
        self.assertNotIn(self.token_secret, json.dumps(result))

    def test_check_validates_manifest_checksum_and_frozen_code_fingerprint(self):
        root = self.tmp / "repo"
        config_dir = root / "pipeline_v2/configs"
        config_dir.mkdir(parents=True)
        shutil.copyfile(deploy_modal.ROOT / "pipeline_v2/configs/m3.json", config_dir / "m3.json")
        self.write_env("")
        run = root / "pipeline_v2/artifacts/fake-plan"
        run.mkdir(parents=True)
        profile = json.loads((config_dir / "m3.json").read_bytes())
        from pipeline_v2.retrieval.common import implementation
        manifest = {"profile": profile, "implementation": implementation()}
        manifest_raw = canonical(manifest)
        (run / "pilot_manifest.json").write_bytes(manifest_raw)
        (run / "manifest.sha256.json").write_bytes(canonical({"sha256": digest(manifest_raw)}))
        result = deploy_modal.check_configuration(root, self.env_file, "pipeline_v2/artifacts/fake-plan", parent_env={})
        self.assertEqual(result["pilot_plan_check"], "frozen_profile_code_and_manifest_checksum_match")

        manifest["implementation"]["pipeline_v2/m3.py"] = "stale-code"
        manifest_raw = canonical(manifest)
        (run / "pilot_manifest.json").write_bytes(manifest_raw)
        (run / "manifest.sha256.json").write_bytes(canonical({"sha256": digest(manifest_raw)}))
        with self.assertRaises(deploy_modal.EnvConfigError):
            deploy_modal.check_configuration(root, self.env_file, "pipeline_v2/artifacts/fake-plan", parent_env={})

    def test_cli_help_is_local_and_never_calls_subprocess(self):
        missing = self.tmp / "does-not-exist.env"
        for argv in (["--env-file", str(missing), "check", "--help"],
                     ["--env-file", str(missing), "deploy", "--help"],
                     ["--env-file", str(missing), "m3", "--help"]):
            with self.subTest(argv=argv):
                with patch.object(deploy_modal.subprocess, "run") as runner:
                    with redirect_stdout(io.StringIO()):
                        with self.assertRaises(SystemExit) as result:
                            deploy_modal.main(argv)
                self.assertEqual(result.exception.code, 0)
                runner.assert_not_called()

    def test_deploy_uses_argument_list_cwd_and_environment_without_token_argv(self):
        self.write_env(
            f'MODAL_TOKEN_ID="{self.token_id}"\n'
            f'MODAL_TOKEN_SECRET="{self.token_secret}"\n'
        )
        before = self.env_file.read_bytes()
        fake_result = subprocess.CompletedProcess([], 0)
        with patch.object(deploy_modal.subprocess, "run", return_value=fake_result) as runner:
            with redirect_stdout(io.StringIO()):
                status = deploy_modal.main(["--env-file", str(self.env_file), "deploy"])
        self.assertEqual(status, 0)
        args, kwargs = runner.call_args
        command = args[0]
        self.assertEqual(command[:3], [sys.executable, "-m", "modal"])
        self.assertEqual(command[3:5], ["deploy", deploy_modal.DEPLOY_FILE])
        self.assertEqual(kwargs["cwd"], deploy_modal.ROOT)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["env"]["MODAL_TOKEN_ID"], self.token_id)
        self.assertEqual(kwargs["env"]["MODAL_TOKEN_SECRET"], self.token_secret)
        self.assertNotIn(self.token_id, command)
        self.assertNotIn(self.token_secret, command)
        self.assertEqual(self.env_file.read_bytes(), before)
        self.assertTrue((deploy_modal.ROOT / deploy_modal.DEPLOY_FILE).is_file())

    def test_m3_forwards_remainder_and_sanitized_environment_to_new_process(self):
        self.write_env(
            f'MODAL_TOKEN_ID="{self.token_id}"\n'
            f'MODAL_TOKEN_SECRET="{self.token_secret}"\n'
            'MODAL_PROFILE=deploy-profile\n'
        )
        fake_result = subprocess.CompletedProcess([], 0)
        with patch.object(deploy_modal.subprocess, "run", return_value=fake_result) as runner:
            with redirect_stdout(io.StringIO()):
                status = deploy_modal.main(["m3", "--env-file", str(self.env_file), "--", "search", "--help"])
        self.assertEqual(status, 0)
        args, kwargs = runner.call_args
        command = args[0]
        self.assertEqual(command, [sys.executable, "-m", "pipeline_v2.m3", "search", "--help"])
        self.assertEqual(kwargs["cwd"], deploy_modal.ROOT)
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["env"]["MODAL_PROFILE"], "deploy-profile")
        self.assertEqual(kwargs["env"]["MODAL_TOKEN_ID"], self.token_id)
        self.assertEqual(kwargs["env"]["MODAL_TOKEN_SECRET"], self.token_secret)
        self.assertNotIn(self.token_id, command)
        self.assertNotIn(self.token_secret, command)

    def test_cli_reports_parser_errors_without_echoing_secret(self):
        self.write_env(f"MODAL_TOKEN_SECRET={self.token_secret}\nUNKNOWN={self.token_secret}\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(deploy_modal.subprocess, "run") as runner, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            status = deploy_modal.main(["--env-file", str(self.env_file), "check"])
        self.assertEqual(status, 2)
        self.assertNotIn(self.token_secret, stdout.getvalue() + stderr.getvalue())
        runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
