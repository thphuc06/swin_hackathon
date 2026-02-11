from __future__ import annotations

import argparse
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests


DEFAULT_BASE_URL = "http://127.0.0.1:8010/chat/stream"
DEFAULT_OUTPUT_FILE = "tools_coverage_test_utf8.txt"


@dataclass
class Case:
    case_id: str
    prompt: str
    expected_tools: list[str]


CASES = [
    Case("C01_15D_SUMMARY", "15 ngày qua dòng tiền của tôi thế nào?", []),
    Case(
        "C02_ANOMALY_THIS_MONTH",
        "Tháng này tôi thấy có giao dịch lạ, bạn kiểm tra giúp.",
        ["anomaly_signals_v1"],
    ),
    Case(
        "C03_ANOMALY_REASON",
        "Tháng này tôi thấy có giao dịch lạ. Hai cảnh báo đó là gì và vì sao bật?",
        ["anomaly_signals_v1"],
    ),
    Case(
        "C04_ANOMALY_2MONTH_DATE",
        "2 tháng gần đây tôi có giao dịch nào bất thường không? Nếu có thì ngày nào?",
        ["anomaly_signals_v1"],
    ),
    Case(
        "C05_GOAL_FEASIBILITY",
        "Tôi muốn tiết kiệm 50 triệu trong 6 tháng, có khả thi không? Gợi ý kế hoạch.",
        [],
    ),
    Case(
        "C06_WHAT_IF",
        "Giả sử thu nhập giảm 20% và chi tiêu tăng 10% trong 6 tháng thì sao?",
        ["what_if_scenario_v1"],
    ),
    Case(
        "C07_INVEST_REFUSAL",
        "Tôi có nên mua cổ phiếu ngân hàng lúc này không?",
        ["suitability_guard_v1"],
    ),
    Case(
        "C08_ANOMALY_TOP3",
        "Tháng này có giao dịch lạ. Hãy liệt kê 3 cảnh báo nổi bật và vì sao bật.",
        ["anomaly_signals_v1"],
    ),
]


def generate_token() -> str:
    proc = subprocess.run(
        ["python", "agent/genToken.py"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("AccessToken:"):
            token = line.replace("AccessToken:", "", 1).strip()
            if token:
                return token
    raise RuntimeError("AccessToken not found from agent/genToken.py")


def parse_sse(response: requests.Response) -> tuple[dict[str, str], str, str]:
    meta = {
        "RuntimeSource": "",
        "ResponseMode": "",
        "ResponseFallback": "",
        "ResponseReasonCodes": "",
        "Trace": "",
        "Tools": "",
        "Citations": "",
        "Disclaimer": "",
    }
    output_lines: list[str] = []
    raw_lines: list[str] = []

    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = str(raw).rstrip("\r")
        raw_lines.append(line)
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue

        matched = False
        for key in meta:
            prefix = f"{key}:"
            if payload.startswith(prefix):
                meta[key] = payload.replace(prefix, "", 1).strip()
                matched = True
                break
        if not matched:
            output_lines.append(payload)

    return meta, "\n".join(output_lines).strip(), "\n".join(raw_lines)


def run(base_url: str, output_file: Path, token: str) -> int:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    lines: list[str] = []
    lines.append("TOOLS COVERAGE TEST REPORT (UTF-8)")
    lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Base URL: {base_url}")
    lines.append("")

    pass_count = 0
    for case in CASES:
        start = time.perf_counter()
        http_status = 0
        status = "PASS"
        checks: list[str] = []
        error_text = ""
        meta = {
            "RuntimeSource": "",
            "ResponseMode": "",
            "ResponseFallback": "",
            "ResponseReasonCodes": "",
            "Trace": "",
            "Tools": "",
            "Citations": "",
            "Disclaimer": "",
        }
        output = ""
        raw_sse = ""

        try:
            resp = requests.post(
                base_url,
                headers=headers,
                json={"prompt": case.prompt},
                stream=True,
                timeout=240,
            )
            http_status = resp.status_code
            if http_status == 200:
                meta, output, raw_sse = parse_sse(resp)
            else:
                status = "FAIL"
                error_text = resp.text
        except Exception as exc:  # noqa: BLE001
            status = "FAIL"
            error_text = f"{type(exc).__name__}: {exc}"

        if http_status == 200:
            checks.append("HTTP_200")
        else:
            checks.append("HTTP_NOT_200")
            status = "FAIL"

        tools = [item.strip() for item in meta["Tools"].split(",") if item.strip()]
        if case.expected_tools:
            missing = [name for name in case.expected_tools if name not in tools]
            if missing:
                checks.append("MISSING_EXPECTED_TOOLS:" + ",".join(missing))
                status = "FAIL"
            else:
                checks.append("HAS_EXPECTED_TOOLS")

        elapsed = time.perf_counter() - start
        if status == "PASS":
            pass_count += 1

        lines.append("=" * 120)
        lines.append(f"[{case.case_id}] {status}")
        lines.append(f"Prompt: {case.prompt}")
        lines.append(
            f"HTTP: {http_status} | Time: {elapsed:.2f}s | Runtime: {meta['RuntimeSource']} | "
            f"Mode: {meta['ResponseMode']} | Fallback: {meta['ResponseFallback']}"
        )
        lines.append(f"ReasonCodes: {meta['ResponseReasonCodes']}")
        lines.append(f"Tools: {meta['Tools']}")
        lines.append(f"Checks: {', '.join(checks)}")
        lines.append(f"Citations: {meta['Citations']}")
        lines.append(f"Trace: {meta['Trace']}")
        lines.append("OutputFull:")
        lines.append(output if output else "<empty>")
        if error_text:
            lines.append("Error:")
            lines.append(error_text)
        lines.append("RAW_SSE:")
        lines.append(raw_sse if raw_sse else "<empty>")
        lines.append("")

    fail_count = len(CASES) - pass_count
    lines.append("=" * 120)
    lines.append("SUMMARY")
    lines.append(f"Cases: {len(CASES)} | PASS: {pass_count} | FAIL: {fail_count}")

    output_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote: {output_file}")
    print(f"PASS={pass_count} FAIL={fail_count}")
    return 0 if fail_count == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run UTF-8 tool coverage cases for /chat/stream.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Chat stream URL (default: %(default)s)")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_FILE,
        help="Output report file path (default: %(default)s)",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Optional bearer token. If omitted, script runs agent/genToken.py.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = args.token.strip() if args.token else generate_token()
    return run(args.base_url, Path(args.output), token)


if __name__ == "__main__":
    raise SystemExit(main())
