from pathlib import Path
from .build import build_execution_suite
if __name__=="__main__":
    p=Path(__file__).resolve().parents[1]
    report=build_execution_suite(plan07_report=p/"reports/plan07_analysis_region_validation.latest.json",execution_policy=p/"policies/execution_policy.v1.json",output_root=p/"outputs/plan08_execution_v1",report_path=p/"reports/plan08_execution_validation.latest.json")
    print(f"Plan 08 {report['status']}: report={report['outputs']['build_manifest']}")
