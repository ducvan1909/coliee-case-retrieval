"""Load four explicit Modal settings locally and launch existing frozen code.

This module never reads or copies SDK profile credentials, and `check` performs
no authentication RPC. Deploy and inference occur only via explicit commands.
"""
import argparse
from importlib import metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ALLOWED_KEYS = frozenset({"MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "MODAL_PROFILE", "MODAL_ENVIRONMENT"})
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = "pipeline_v2/.env"
DEPLOY_FILE = "pipeline_v2/deployments/modal/qwen3_embed.py"
DEFAULT_RUN = "pipeline_v2/artifacts/m3_pilot_20261106_l4_v1"


class EnvConfigError(ValueError):
    """Safe configuration error: messages contain no setting values."""


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid argument values, which can include
        # accidentally pasted credentials. Keep its exit code without that echo.
        self.exit(2, "Invalid deploy helper arguments. Use --help.\n")


def _value(raw, line_number):
    raw = raw.strip()
    if not raw or raw.startswith("#"):
        return ""
    if raw[0] in ("'", '"'):
        quote = raw[0]
        end = raw.find(quote, 1)
        if end < 0:
            raise EnvConfigError(f"Unbalanced quote at line {line_number}")
        tail = raw[end+1:].strip()
        if tail and not tail.startswith("#"):
            raise EnvConfigError(f"Unexpected text after quote at line {line_number}")
        value = raw[1:end]
    else:
        value = re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
        if "'" in value or '"' in value:
            raise EnvConfigError(f"Quotes must surround the whole value at line {line_number}")
    if "\x00" in value:
        raise EnvConfigError(f"Invalid environment value at line {line_number}")
    return value


def parse_env(path):
    """Parse a deliberately small dotenv grammar, without shell semantics."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise EnvConfigError("Cannot read UTF-8 env file: "+type(exc).__name__) from None
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in line:
            raise EnvConfigError(f"Expected KEY=value at line {number}")
        key, raw = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_KEYS:
            raise EnvConfigError(f"Unknown setting at line {number}")
        if key in values:
            raise EnvConfigError(f"Duplicate setting at line {number}")
        values[key] = _value(raw, number)
    return values


def _pair(values, source):
    present = [bool(values.get(key)) for key in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")]
    if present[0] != present[1]:
        raise EnvConfigError(f"Both Modal token settings must be present or blank in {source}")


def build_environment(values, parent_env=None):
    """Nonempty file values override a copy; blanks retain process/SDK auth."""
    if set(values)-ALLOWED_KEYS:
        raise EnvConfigError("Unsupported environment setting")
    if any(not isinstance(value, str) or "\x00" in value or "\n" in value or "\r" in value for value in values.values()):
        raise EnvConfigError("Invalid environment value")
    _pair(values, "env file")
    environment = dict(os.environ if parent_env is None else parent_env)
    environment.update({key:value for key,value in values.items() if value})
    _pair(environment, "effective environment")
    return environment


def _path(root, path):
    path = Path(path)
    return path if path.is_absolute() else Path(root)/path


def check_configuration(repo_root, env_file=DEFAULT_ENV, run_dir=None, parent_env=None):
    """Read-only validation; no SDK import, profile-secret reads or network."""
    root = Path(repo_root).resolve()
    environment = build_environment(parse_env(_path(root, env_file)), parent_env)
    from .retrieval.common import implementation, load_profile
    from .source.core import digest
    profile = load_profile(root)
    try:
        version = metadata.version("modal")
    except metadata.PackageNotFoundError:
        raise EnvConfigError("Modal package is not installed") from None
    if version != "1.5.3":
        raise EnvConfigError("Modal package version differs from pinned local requirements")
    candidate = _path(root, run_dir or DEFAULT_RUN).resolve()
    plan_status = "not_checked_no_default_plan"
    manifest_path = candidate/"pilot_manifest.json"
    if run_dir is not None or manifest_path.exists():
        try:
            manifest_raw = manifest_path.read_bytes()
            manifest = json.loads(manifest_raw)
            seal = json.loads((candidate/"manifest.sha256.json").read_bytes())
        except (OSError, ValueError, UnicodeError) as exc:
            raise EnvConfigError("Cannot read pilot plan: "+type(exc).__name__) from None
        if (seal != {"sha256":digest(manifest_raw)} or manifest.get("profile") != profile or
                manifest.get("implementation") != implementation()):
            raise EnvConfigError("Frozen M3 pilot profile/code or manifest checksum drift")
        plan_status = "frozen_profile_code_and_manifest_checksum_match"
    tokens = bool(environment.get("MODAL_TOKEN_ID"))
    def label(value):
        # Profile/environment labels are useful metadata, but an accidentally
        # pasted token in either field must still never be echoed by `check`.
        if any(secret and secret in value for secret in
               (environment.get("MODAL_TOKEN_ID"), environment.get("MODAL_TOKEN_SECRET"))):
            return "[redacted]"
        return value
    return {
        "status":"local_configuration_only",
        "authentication_verified":False,
        "network_requests":0,
        "auth_mode":"environment_token_pair" if tokens else "sdk_profile",
        "profile":label(environment.get("MODAL_PROFILE") or "active_or_default_sdk_profile"),
        "environment":label(environment.get("MODAL_ENVIRONMENT") or "sdk_default_environment"),
        "modal_version":version,
        "model":profile["embedding"]["model"],
        "model_revision":profile["embedding"]["revision"],
        "app":profile["embedding"]["modal_app"],
        "pilot_plan_check":plan_status,
    }


def main(argv=None):
    parser = _SafeArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=DEFAULT_ENV)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "deploy", "m3"):
        p = commands.add_parser(name)
        p.add_argument("--env-file", default=argparse.SUPPRESS)
        if name == "check":
            p.add_argument("--run-dir")
        if name == "m3":
            p.add_argument("m3_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        # Run the local frozen-code/config check for every entry point, before
        # passing credentials into a child process. It deliberately makes no RPC.
        result = check_configuration(ROOT, args.env_file, getattr(args, "run_dir", None))
        if args.command == "check":
            print(json.dumps(result, ensure_ascii=True, sort_keys=True))
            return 0
        environment = build_environment(parse_env(_path(ROOT, args.env_file)))
        if args.command == "deploy":
            command = [sys.executable, "-m", "modal", "deploy", DEPLOY_FILE]
        else:
            forwarded = list(args.m3_args)
            if forwarded[:1] == ["--"]:
                forwarded = forwarded[1:]
            if not forwarded:
                raise EnvConfigError("m3 requires a subcommand or --help")
            command = [sys.executable, "-m", "pipeline_v2.m3", *forwarded]
        # Inherit the terminal streams; never capture child output into a report
        # containing an environment dump or API credentials.
        return subprocess.run(command, env=environment, cwd=ROOT, shell=False).returncode
    except EnvConfigError as exc:
        print(json.dumps({"status":"error", "error":str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        # Third-party exception text/repr may contain secret-bearing env values.
        print(json.dumps({"status":"error", "error_type":type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
