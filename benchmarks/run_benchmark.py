"""Benchmark search quality and latency for each ranking mode.

    py -3 benchmarks/run_benchmark.py                 # all modes
    py -3 benchmarks/run_benchmark.py --modes hybrid  # just one

Writes benchmarks/results.json and benchmarks/results.md. Each mode runs in a
fresh process because the ranking mode is fixed when the backend is imported.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "backend"
DATASET = HERE / "benchmark_queries.json"

MODES = {
    # mode name: environment for that run
    "hybrid": {"RERANKING_MODE": "hybrid"},
    "xgboost": {"RERANKING_MODE": "xgboost"},
    "cross_encoder": {"RERANKING_MODE": "cross_encoder", "CROSS_ENCODER_ENABLED": "true"},
}


def _run_mode(out_path: Path) -> None:
    """Child process: run every case with the mode given by the environment."""
    sys.path.insert(0, str(BACKEND))
    os.environ.setdefault("SEARCH_TELEMETRY_ENABLED", "false")
    from kb_manager import KnowledgeRegistry, bind_registry
    from kb_search import search_kb_with_outlier_gate
    from embedding_model import SentenceTransformer

    registry = KnowledgeRegistry(SentenceTransformer("all-MiniLM-L6-v2"))
    bind_registry(registry)
    registry.reload_all()

    cases = json.loads(DATASET.read_text(encoding="utf-8"))["cases"]
    search_kb_with_outlier_gate(cases[0]["query"], cases[0]["caller_type"])  # warm-up
    rows = []
    for case in cases:
        start = time.perf_counter()
        payload = search_kb_with_outlier_gate(case["query"], case["caller_type"], top_k=5)
        latency_ms = (time.perf_counter() - start) * 1000
        ids = [r.get("branch_id") for r in payload.get("results") or []]
        rank = ids.index(case["expected_branch_id"]) + 1 if case["expected_branch_id"] in ids else None
        rows.append(
            {
                "id": case["id"],
                "query": case["query"],
                "style": case["query_style"],
                "status": payload.get("status"),
                "rank": rank,
                "top1": ids[0] if ids else None,
                "expected": case["expected_branch_id"],
                "latency_ms": round(latency_ms, 2),
            }
        )
    out_path.write_text(json.dumps(rows), encoding="utf-8")


def _summarize(rows: list[dict]) -> dict:
    def hit(k: int, subset: list[dict]) -> float:
        return round(100 * sum(1 for r in subset if r["rank"] and r["rank"] <= k) / len(subset), 1)

    latencies = sorted(r["latency_ms"] for r in rows)
    summary = {
        "cases": len(rows),
        "top1": hit(1, rows),
        "top3": hit(3, rows),
        "top5": hit(5, rows),
        "mrr": round(sum(1 / r["rank"] for r in rows if r["rank"]) / len(rows), 4),
        "median_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(latencies[int(0.95 * (len(latencies) - 1))], 1),
        "by_style": {},
    }
    for style in sorted({r["style"] for r in rows}):
        subset = [r for r in rows if r["style"] == style]
        summary["by_style"][style] = {"cases": len(subset), "top1": hit(1, subset), "top3": hit(3, subset)}
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", nargs="*", default=list(MODES))
    parser.add_argument("--child", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        _run_mode(Path(args.child))
        return

    results = {}
    for mode in args.modes:
        out = HERE / f".tmp_{mode}.json"
        env = {**os.environ, **MODES[mode], "PYTHONHASHSEED": "0"}
        print(f"Running {mode} ...", flush=True)
        subprocess.run([sys.executable, __file__, "--child", str(out)], env=env, cwd=BACKEND, check=True)
        rows = json.loads(out.read_text(encoding="utf-8"))
        out.unlink()
        results[mode] = {"summary": _summarize(rows), "misses": [r for r in rows if r["rank"] != 1]}
        print(f"  {mode}: {results[mode]['summary']}")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (HERE / "results.json").write_text(
        json.dumps({"generated": generated, "results": results}, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    lines = [
        "# Search benchmark",
        "",
        f"Generated {generated} on a local CPU. {next(iter(results.values()))['summary']['cases']} queries over the synthetic",
        "Northwind Marketplace knowledge base: two hand-written caller phrasings per issue (never",
        "the issue title) plus one typo variant. Regenerate with `py -3 benchmarks/run_benchmark.py`.",
        "",
        "| Ranking mode | Top-1 | Top-3 | Top-5 | MRR | Top-1 paraphrase | Top-1 typo | Median ms | P95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, data in results.items():
        s = data["summary"]
        lines.append(
            f"| {mode} | {s['top1']}% | {s['top3']}% | {s['top5']}% | {s['mrr']} | "
            f"{s['by_style'].get('paraphrase', {}).get('top1', '-')}% | {s['by_style'].get('typo', {}).get('top1', '-')}% | "
            f"{s['median_ms']} | {s['p95_ms']} |"
        )
    lines += ["", "Synthetic data, single machine, no production traffic: treat these as relative, not absolute."]
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("Wrote benchmarks/results.md")


if __name__ == "__main__":
    main()
