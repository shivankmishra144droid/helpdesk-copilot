# Search benchmark

Generated 2026-10-01 19:13 UTC on a local CPU. 198 queries over the synthetic
Northwind Marketplace knowledge base: two hand-written caller phrasings per issue (never
the issue title) plus one typo variant. Regenerate with `py -3 benchmarks/run_benchmark.py`.

| Ranking mode | Top-1 | Top-3 | Top-5 | MRR | Top-1 paraphrase | Top-1 typo | Median ms | P95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hybrid | 86.4% | 100.0% | 100.0% | 0.9251 | 87.1% | 84.8% | 38.7 | 56.1 |
| xgboost | 84.8% | 95.5% | 96.5% | 0.9015 | 85.6% | 83.3% | 66.1 | 78.1 |
| cross_encoder | 93.4% | 98.5% | 99.5% | 0.9621 | 93.9% | 92.4% | 278.1 | 385.8 |

Synthetic data, single machine, no production traffic: treat these as relative, not absolute.
