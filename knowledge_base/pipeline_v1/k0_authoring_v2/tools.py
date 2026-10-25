"""Case-local navigation with conservative current-active assessment."""
from __future__ import annotations

from ..k0_authoring import tools as old
from .core import require

initial_state = old.initial_state
open_region, search_source, get_drafts = old.open_region, old.search_source, old.get_drafts


def apply_turn(case, state, normalized):
    result = old.apply_turn(case, state, normalized)
    # Earlier assessment cannot mask a current missing-context/navigation response.
    for sid in normalized['unresolved_scope_ids']:
        result['read_ledger'][sid].update(state='unresolved', assessed=False)
    for sid in normalized['delivered_scope_ids']:
        result['read_ledger'][sid]['assessment_result'] = normalized['assessment_result']
    result['work_scope_complete'] = (result['finished']
        and result['stop_reason'] == 'work_scope_complete'
        and all(r['assessed'] and r['state'] == 'assessed' for r in result['read_ledger'].values()))
    result['case_source_assessment_complete'] = False
    result['case_status'] = 'partial'
    return result
