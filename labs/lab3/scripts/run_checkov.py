#!/usr/bin/env python3
import json, subprocess, argparse, sys, os
from pathlib import Path

root = Path(__file__).resolve().parent.parent
reports = root / "reports"
reports.mkdir(exist_ok=True)


def build_cmd():
    cmd = [
        "checkov",
        "-d", str(root / "terraform"),
        "-d", str(root / "k8s"),
        "-d", str(root / "docker"),
        "--output", "json", "--skip-download",
    ]
    # TODO: adjust directories/output flags if you introduce new IaC targets or prefer SARIF output.
    return cmd


def decode_reports(text):
    """Checkov emits one JSON document per -d target; normalize to one array."""
    decoder = json.JSONDecoder()
    reports = []
    rest = text.strip()
    if not rest:
        raise ValueError('Checkov returned empty output')
    while rest:
        obj, end = decoder.raw_decode(rest)
        if not isinstance(obj, (dict, list)):
            raise ValueError('Checkov returned a non-report JSON value')
        reports.extend(obj if isinstance(obj, list) else [obj])
        rest = rest[end:].lstrip()
    # This Checkov version emits cumulative snapshots between directories.
    unique = {}
    for report in reports:
        unique[json.dumps(report, sort_keys=True)] = report
    return list(unique.values())


def run(after: bool = False, *, runner=subprocess.run, report_dir: Path = reports) -> Path:
    out = report_dir / ("checkov_after.json" if after else "checkov.json")
    os.environ["CKV_SKIP_MAPPING"] = "true"
    os.environ["CHECKOV_ENABLE_VERSION_CHECK"] = "false"
    try:
        res = runner(build_cmd(), capture_output=True, text=True, check=False)
        text = res.stdout.strip()
        if res.returncode not in (0, 1):
            raise RuntimeError("checkov failed with exit code " + str(res.returncode) + ": " + res.stderr[-2000:])
        data = decode_reports(text)
        text = json.dumps(data[0] if len(data)==1 else data, indent=2)
        if not isinstance(data, (dict, list)):
            raise ValueError("Scanner output must be a JSON object or array")
        report_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Wrote {out}")
    except FileNotFoundError:
        print("Checkov not found. Install with: pip install checkov", file=sys.stderr)
        sys.exit(2)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--after", action="store_true", help="Write *_after.json")
    args = parser.parse_args()
    run(after=args.after)


if __name__ == "__main__":
    main()
