#!/usr/bin/env python3
import json, subprocess, argparse, sys, os
from pathlib import Path

root = Path(__file__).resolve().parent.parent
reports = root / "reports"
reports.mkdir(exist_ok=True)


def build_cmd():
    cmd = [
        "semgrep",
        "--config", str(root / "config" / "semgrep_rules.yml"),
        "--json", "--metrics=off", "--disable-version-check",
        str(root / "terraform"), str(root / "k8s"), str(root / "docker"),
    ]
    # TODO: narrow or expand targets/configs here to reflect the IaC stack your team is responsible for.
    return cmd


def run(after: bool = False, *, runner=subprocess.run, report_dir: Path = reports) -> Path:
    out = report_dir / ("semgrep_after.json" if after else "semgrep.json")
    os.environ["CKV_SKIP_MAPPING"] = "true"
    os.environ["CHECKOV_ENABLE_VERSION_CHECK"] = "false"
    try:
        res = runner(build_cmd(), capture_output=True, text=True, check=False)
        text = res.stdout.strip()
        if res.returncode not in (0, 1):
            raise RuntimeError("semgrep failed with exit code " + str(res.returncode) + ": " + res.stderr[-2000:])
        data = json.loads(text)  # A successful process with broken JSON is not a valid replay.
        if not isinstance(data, (dict, list)):
            raise ValueError("Scanner output must be a JSON object or array")
        report_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out}")
    except FileNotFoundError:
        print("Semgrep not found. Install with: pip install semgrep", file=sys.stderr)
        sys.exit(2)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--after", action="store_true", help="Write *_after.json")
    args = parser.parse_args()
    run(after=args.after)


if __name__ == "__main__":
    main()
