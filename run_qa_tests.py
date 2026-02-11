from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_TEST_USER_ID = "64481438-5011-7008-00f8-03e42cc06593"
RUNTIME_RESULTS_FILE = "test_results_runtime_stream.txt"
SUMMARY_RESULTS_FILE = "results.txt"


@dataclass
class CaseResult:
    case_id: str
    prompt: str
    http_status: int
    elapsed_sec: float
    runtime: str
    mode: str
    fallback: str
    reason_codes: str
    trace: str
    tools: list[str]
    citations: list[str]
    disclaimer: str
    output: str
    raw_sse: str
    checks: list[str] = field(default_factory=list)
    status: str = "PASS"


TEST_CASES = [
    {"id": "CASE_01", "prompt": "Tom tat chi tieu 30 ngay qua cua toi."},
    {"id": "CASE_02", "prompt": "Chi tieu cua toi thang nay la bao nhieu? So voi thang truoc tang hay giam?"},
    {"id": "CASE_03", "prompt": "Toi muon toi uu tai chinh ca nhan."},
    {"id": "CASE_04", "prompt": "Toi muon tiet kiem 50 trieu trong 6 thang, co kha thi khong? Goi y ke hoach."},
    {"id": "CASE_05", "prompt": "Toi hay co khoan chi co dinh moi thang, giup toi nhan dien va toi uu."},
    {"id": "CASE_06", "prompt": "Thang nay toi thay co giao dich la, ban kiem tra giup."},
    {"id": "CASE_07", "prompt": "Gia su thu nhap giam 20% va chi tieu tang 10% trong 6 thang thi sao?"},
    {"id": "CASE_08", "prompt": "Toi co nen mua co phieu ngan hang luc nay khong?"},
    {"id": "CASE_09", "prompt": "Toi muon mua nha 1.5 ty trong 5 nam, ke hoach tiet kiem kha thi?"},
    {"id": "CASE_10", "prompt": "Ke chuyen cuoi di."},
    {"id": "CASE_11", "prompt": "Toi tieu gi vao ngay 31/02?"},
    {"id": "CASE_12", "prompt": "Neu dong tien am keo dai, toi nen uu tien dich vu ngan hang nao truoc?"},
]


def generate_token() -> str:
    cmd = [sys.executable, "agent/genToken.py"]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=True)
    for line in result.stdout.splitlines():
        if line.startswith("AccessToken:"):
            return line.replace("AccessToken:", "").strip()
    raise RuntimeError("Cannot find AccessToken in agent/genToken.py output.")


def parse_sse_response(response: requests.Response) -> Dict[str, object]:
    runtime = ""
    mode = ""
    fallback = ""
    reason_codes = ""
    trace = ""
    tools: list[str] = []
    citations: list[str] = []
    disclaimer = ""
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
        if payload.startswith("RuntimeSource:"):
            runtime = payload.replace("RuntimeSource:", "", 1).strip()
            continue
        if payload.startswith("ResponseMode:"):
            mode = payload.replace("ResponseMode:", "", 1).strip()
            continue
        if payload.startswith("ResponseFallback:"):
            fallback = payload.replace("ResponseFallback:", "", 1).strip()
            continue
        if payload.startswith("ResponseReasonCodes:"):
            reason_codes = payload.replace("ResponseReasonCodes:", "", 1).strip()
            continue
        if payload.startswith("Trace:"):
            trace = payload.replace("Trace:", "", 1).strip()
            continue
        if payload.startswith("Tools:"):
            tools_text = payload.replace("Tools:", "", 1).strip()
            tools = [item.strip() for item in tools_text.split(",") if item.strip()]
            continue
        if payload.startswith("Citations:"):
            cite_text = payload.replace("Citations:", "", 1).strip()
            citations = [item.strip() for item in cite_text.split(",") if item.strip()]
            continue
        if payload.startswith("Disclaimer:"):
            disclaimer = payload.replace("Disclaimer:", "", 1).strip()
            continue
        output_lines.append(payload)

    return {
        "runtime": runtime,
        "mode": mode,
        "fallback": fallback,
        "reason_codes": reason_codes,
        "trace": trace,
        "tools": tools,
        "citations": citations,
        "disclaimer": disclaimer,
        "output": "\n".join(output_lines).strip(),
        "raw_sse": "\n".join(raw_lines),
    }


def _check(condition: bool, success: str, failure: str, checks: list[str]) -> bool:
    checks.append(success if condition else failure)
    return condition


def evaluate_case(case: CaseResult) -> CaseResult:
    checks: list[str] = []
    ok = True
    ok = _check(case.http_status == 200, "HTTP_200", "HTTP_NOT_200", checks) and ok

    if case.case_id == "CASE_05":
        ok = _check(
            "recurring_cashflow_detect_v1" in case.tools,
            "HAS_RECURRING_TOOL",
            "MISSING_RECURRING_TOOL",
            checks,
        ) and ok

    if case.case_id == "CASE_06":
        ok = _check(
            "anomaly_signals_v1" in case.tools,
            "HAS_ANOMALY_TOOL",
            "MISSING_ANOMALY_TOOL",
            checks,
        ) and ok
        ok = _check(
            case.fallback != "suitability_refusal",
            "NO_SUITABILITY_REFUSAL",
            "UNEXPECTED_SUITABILITY_REFUSAL",
            checks,
        ) and ok

    if case.case_id == "CASE_08":
        ok = _check(
            case.fallback == "suitability_refusal",
            "EXPECTED_SUITABILITY_REFUSAL",
            "MISSING_SUITABILITY_REFUSAL",
            checks,
        ) and ok

    if case.case_id == "CASE_09":
        ok = _check(
            case.fallback != "suitability_refusal",
            "NO_SUITABILITY_REFUSAL",
            "UNEXPECTED_SUITABILITY_REFUSAL",
            checks,
        ) and ok
        ok = _check(
            "goal_feasibility_v1" in case.tools and "recurring_cashflow_detect_v1" in case.tools,
            "HAS_PLANNING_TOOLSET",
            "MISSING_PLANNING_TOOLSET",
            checks,
        ) and ok

    if case.case_id in {"CASE_06", "CASE_07", "CASE_09", "CASE_12"}:
        ok = _check(
            len(case.citations) > 0,
            "HAS_CITATIONS",
            "MISSING_CITATIONS",
            checks,
        ) and ok

    case.checks = checks
    case.status = "PASS" if ok else "FAIL"
    return case


def write_runtime_results(path: Path, base_url: str, results: List[CaseResult]) -> None:
    lines: list[str] = []
    lines.append(f"Runtime stream test started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Base URL: {base_url}")
    lines.append(f"Cases: {len(results)}")
    lines.append("")
    for idx, case in enumerate(results, start=1):
        lines.append("=" * 90)
        lines.append(f"[{idx}] PROMPT")
        lines.append(case.prompt)
        lines.append(f"HTTP: {case.http_status}")
        lines.append(f"TIME: {case.elapsed_sec:.2f}s")
        lines.append("META:")
        lines.append(f"- runtime: {case.runtime}")
        lines.append(f"- mode: {case.mode}")
        lines.append(f"- fallback: {case.fallback}")
        lines.append(f"- reason_codes: {case.reason_codes}")
        lines.append(f"- trace: {case.trace}")
        lines.append(f"- tools: {', '.join(case.tools)}")
        lines.append(f"- citations: {', '.join(case.citations)}")
        lines.append(f"- disclaimer: {case.disclaimer}")
        lines.append(f"- checks: {', '.join(case.checks)}")
        lines.append(f"STATUS: {case.status}")
        lines.append("")
        lines.append("OUTPUT:")
        lines.append(case.output)
        lines.append("")
        lines.append("RAW_SSE:")
        lines.append(case.raw_sse)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary_results(path: Path, source_file: Path, results: List[CaseResult]) -> None:
    total = len(results)
    pass_count = sum(1 for item in results if item.status == "PASS")
    fail_count = total - pass_count
    lines: list[str] = []
    lines.append(f"Results summary generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Source file: {source_file.name}")
    lines.append(f"Total cases: {total}")
    lines.append(f"PASS: {pass_count}")
    lines.append(f"FAIL: {fail_count}")
    lines.append("")
    lines.append("Per-case summary")
    lines.append("-" * 90)
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"[{idx:02d}] {item.status} | HTTP {item.http_status} | {item.elapsed_sec:.2f}s | "
            f"runtime={item.runtime} | mode={item.mode} | fallback={item.fallback}"
        )
        lines.append(f"Prompt: {item.prompt}")
        lines.append(f"Tools: {', '.join(item.tools)}")
        lines.append(f"Citations: {', '.join(item.citations)}")
        lines.append(f"Checks: {', '.join(item.checks)}")
        preview = item.output.replace("\n", " ")
        if len(preview) > 260:
            preview = preview[:257] + "..."
        lines.append(f"Output preview: {preview}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_cases(base_url: str, token: str, auth_header_enabled: bool = True) -> List[CaseResult]:
    results: list[CaseResult] = []
    stream_url = f"{base_url.rstrip('/')}/chat/stream"
    headers = {"Content-Type": "application/json"}
    if auth_header_enabled:
        headers["Authorization"] = f"Bearer {token}"

    for case in TEST_CASES:
        start = time.perf_counter()
        http_status = 0
        parsed: Dict[str, object] = {
            "runtime": "",
            "mode": "",
            "fallback": "",
            "reason_codes": "",
            "trace": "",
            "tools": [],
            "citations": [],
            "disclaimer": "",
            "output": "",
            "raw_sse": "",
        }
        try:
            response = requests.post(
                stream_url,
                headers=headers,
                json={"prompt": case["prompt"]},
                stream=True,
                timeout=240,
            )
            http_status = response.status_code
            if response.status_code == 200:
                parsed = parse_sse_response(response)
            else:
                parsed["output"] = response.text
        except Exception as exc:  # noqa: BLE001
            parsed["output"] = f"Request error: {type(exc).__name__}: {exc}"

        elapsed = time.perf_counter() - start
        result = CaseResult(
            case_id=case["id"],
            prompt=case["prompt"],
            http_status=http_status,
            elapsed_sec=elapsed,
            runtime=str(parsed.get("runtime") or ""),
            mode=str(parsed.get("mode") or ""),
            fallback=str(parsed.get("fallback") or ""),
            reason_codes=str(parsed.get("reason_codes") or ""),
            trace=str(parsed.get("trace") or ""),
            tools=list(parsed.get("tools") or []),
            citations=list(parsed.get("citations") or []),
            disclaimer=str(parsed.get("disclaimer") or ""),
            output=str(parsed.get("output") or ""),
            raw_sse=str(parsed.get("raw_sse") or ""),
        )
        results.append(evaluate_case(result))
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run 12 runtime stream QA cases against backend /chat/stream.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL (default: %(default)s)")
    parser.add_argument(
        "--token",
        default="",
        help="Cognito access token. If omitted, script will run agent/genToken.py to fetch one.",
    )
    parser.add_argument(
        "--no-auth-header",
        action="store_true",
        help="Skip Authorization header (useful when backend DEV_BYPASS_AUTH=true).",
    )
    parser.add_argument(
        "--runtime-results",
        default=RUNTIME_RESULTS_FILE,
        help="Detailed runtime output file path (default: %(default)s)",
    )
    parser.add_argument(
        "--summary-results",
        default=SUMMARY_RESULTS_FILE,
        help="Summary output file path (default: %(default)s)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime_path = Path(args.runtime_results)
    summary_path = Path(args.summary_results)

    if args.no_auth_header:
        token = ""
    else:
        token = args.token.strip() if args.token else generate_token()
        if not token:
            raise RuntimeError("Token is required when Authorization header is enabled.")

    results = run_cases(args.base_url, token, auth_header_enabled=not args.no_auth_header)
    write_runtime_results(runtime_path, args.base_url, results)
    write_summary_results(summary_path, runtime_path, results)

    pass_count = sum(1 for item in results if item.status == "PASS")
    fail_count = len(results) - pass_count
    print(f"Completed {len(results)} cases. PASS={pass_count}, FAIL={fail_count}")
    print(f"Detailed: {runtime_path}")
    print(f"Summary: {summary_path}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
