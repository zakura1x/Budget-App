"""
Check the AI companion's model connection from this machine (misc/AI, Phase A1).

    python scripts/ai_health.py                 # credentials + one tiny model call
    python scripts/ai_health.py --measure 20    # then 20 timed calls, p50 / p95
    python scripts/ai_health.py --json

Reads .env like the app. Needs AI_ENABLED=True, COMPANY_NAME and
IAM_MANAGEMENT_URL (copied from STWRD's .env), and the watsonx SDK installed.
It fetches the key from IAM exactly as the app does and prints only what each
check found - never the key.

--measure sends a made-up budget summary of about 600 tokens, the size of an
A2 facts block, so the timing matches what a real question costs. No user's
data is read or sent. The Phase A1 gate is p95 under 5 seconds.

Exit code: 0 when every check passes, 1 otherwise.
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Invented figures only. Repeated to reach roughly the size of a facts block.
_SAMPLE_FACTS = (
    "Budget for 1-31 Oct: PHP 25,000.00. Spent so far: PHP 14,200.00. Left: PHP 10,800.00 "
    "over 17 days, PHP 635.29 a day. Food: PHP 5,100.00 of PHP 6,000.00. Transport: PHP 2,300.00 "
    "of PHP 3,000.00. Bills due before 15 Oct: electricity PHP 2,450.00 on 8 Oct, internet PHP "
    "1,699.00 on 10 Oct. Cash on hand: PHP 32,400.00, of which PHP 8,000.00 is set aside for goals. "
)
_MEASURE_PROMPT = (
    "You are a budget assistant. Using only the facts below, answer in two sentences: "
    "how much is left in the budget, and is the user on track?\n\nFacts:\n" + _SAMPLE_FACTS * 5
)


def _percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def measure(count: int) -> dict:
    from app.ai import llm_service
    from app.core.config import settings

    service = llm_service.get_llm_service()
    timings, failures, prompt_tokens = [], 0, []
    for _ in range(count):
        started = time.perf_counter()
        try:
            _text, usage = service.invoke_with_recovery(
                settings.WATSONX_CHAT_MODEL,
                {"max_new_tokens": 120, "temperature": 0.3, "top_p": settings.WATSONX_TOP_P},
                _MEASURE_PROMPT,
                max_retries=1,
            )
            timings.append(int((time.perf_counter() - started) * 1000))
            prompt_tokens.append(int(usage.get("prompt_tokens") or 0))
        except Exception as error:
            failures += 1
            print(f"  call failed: {llm_service.describe_model_error(error)}", file=sys.stderr)
    if not timings:
        return {"calls": count, "failures": failures}
    return {
        "calls": count,
        "failures": failures,
        "prompt_tokens": int(statistics.mean(prompt_tokens)),
        "p50_ms": _percentile(timings, 0.5),
        "p95_ms": _percentile(timings, 0.95),
        "max_ms": max(timings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--measure", type=int, default=0, metavar="N", help="time N model calls after the checks")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    from app.ai import llm_service

    report = llm_service.health(check_model=True)
    if report["status"] == "ok" and args.measure > 0:
        report["measure"] = measure(args.measure)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"AI companion: {report['status']}  (model {report['model']}, company {report['company'] or '-'})")
        for name, check in report["checks"].items():
            mark = "ok " if check.get("ok") else "FAIL"
            ms = f"  {check['ms']} ms" if "ms" in check else ""
            print(f"  [{mark}] {name}: {check['detail']}{ms}")
        if report["status"] == "disabled":
            print("  AI_ENABLED is false in .env - nothing was loaded or called.")
        if "measure" in report:
            m = report["measure"]
            if "p50_ms" in m:
                print(f"  measure: {m['calls']} calls, {m['failures']} failed, ~{m['prompt_tokens']} prompt tokens, "
                      f"p50 {m['p50_ms']} ms, p95 {m['p95_ms']} ms, max {m['max_ms']} ms")
            else:
                print(f"  measure: all {m['calls']} calls failed")

    ok = report["status"] == "ok" and report.get("measure", {}).get("failures", 0) == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
