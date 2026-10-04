import os
import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if '--child' in sys.argv:
    sys.path.insert(0, str(ROOT / 'benchmarks'))
    import run_benchmark
    run_benchmark._run_mode(Path(sys.argv[-1]))
    import psutil
    print(json.dumps({'rss_mb': round(psutil.Process().memory_info().rss / 1024**2, 1), 'torch_imported': 'torch' in sys.modules}))
else:
    reports = {}
    for backend in ['torch', 'onnx']:
        out = ROOT / 'benchmarks' / f'.render-{backend}.json'
        env = {**os.environ, 'EMBEDDING_BACKEND': backend, 'DISABLE_XGBOOST': 'true', 'RERANKING_MODE': 'hybrid', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'TOKENIZERS_PARALLELISM': 'false'}
        result = subprocess.run([sys.executable, __file__, '--child', str(out)], env=env, cwd=ROOT, capture_output=True, text=True)
        print(backend, result.stdout, result.stderr[-2000:], flush=True)
        result.check_returncode()
        reports[backend] = {'rows': json.loads(out.read_text()), 'memory': json.loads(result.stdout.strip().splitlines()[-1])}
        out.unlink()
    sys.path.insert(0, str(ROOT / 'benchmarks'))
    from run_benchmark import _summarize
    summary = {k: {**_summarize(v['rows']), **v['memory']} for k,v in reports.items()}
    summary['top1_agreement'] = sum(a['top1'] == b['top1'] for a,b in zip(reports['torch']['rows'], reports['onnx']['rows']))
    summary['rank_agreement'] = sum(a['rank'] == b['rank'] for a,b in zip(reports['torch']['rows'], reports['onnx']['rows']))
    summary['note'] = 'Windows backend RSS after 198 searches; excludes Node and is not a Linux container memory guarantee.'
    (ROOT / 'benchmarks/render_results.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
