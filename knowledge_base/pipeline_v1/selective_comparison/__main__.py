import argparse
from pathlib import Path
from ..milestone1.core import load
from .core import compare


def main():
    p=argparse.ArgumentParser(description='Compare selective reading with frozen same-target model reference, not gold')
    p.add_argument('--manifest',required=True);p.add_argument('--baseline',required=True)
    p.add_argument('--h-run');p.add_argument('--p-run');p.add_argument('--output-root',required=True)
    a=p.parse_args()
    if not a.h_run and not a.p_run:p.error('Provide --h-run or --p-run')
    root=Path(a.output_root).resolve()
    deps=[a.manifest,a.baseline,a.h_run,a.p_run]
    if any(root==Path(x).resolve().parent or Path(x).resolve().is_relative_to(root) for x in deps if x):
        p.error('Use a separate comparison directory outside input artifacts')
    try:
        report=compare(load(a.manifest),load(a.baseline),{k:load(v) for k,v in [('H',a.h_run),('P',a.p_run)] if v},root)
        print(f'SELECTIVE COMPARISON READY targets={report["targets"]} — {root/"comparison.json"}');return 0
    except ValueError as e:
        safe=str(e);print('SELECTIVE COMPARISON ERROR '+(safe if safe.replace('_','').isalnum() else type(e).__name__));return 2


if __name__=='__main__':raise SystemExit(main())
