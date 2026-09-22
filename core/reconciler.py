"""Auto-Reconciliation Daemon for SunkGuard.

Runs automatically when connectivity transitions from DISCONNECTED to ONLINE:
1. Identifies workflows frozen in OFFLINE_PAUSED state during the outage.
2. Unfreezes them to resume at the exact stalled step with zero token waste.
3. Drains workflows queued offline from OFFLINE_JOURNAL in SunkGuard priority order.
4. Updates audit logs and marks journal entries as RECONCILED.
"""

import threading
import time
from typing import Any, Dict, List, Optional

from core.canonical import CanonicalEventType
from core.connectivity import CONNECTIVITY, ConnectivityState
from core.offline_journal import OFFLINE_JOURNAL


class AutoReconciler:
    """Synchronizes stored offline state, unfreezes paused agents, and flushes queues."""

    def __init__(self, runtime_manager: Optional[Any] = None):
        self._runtime = runtime_manager
        self.is_reconciling: bool = False
        self.last_reconciliation_result: Dict[str, Any] = {
            "status": "none",
            "unfrozen_workflows": 0,
            "drained_offline_workflows": 0,
        }
        self._lock = threading.Lock()
        # Subscribe to connectivity changes
        CONNECTIVITY.subscribe(self._on_connectivity_change)

    @property
    def runtime(self):
        if self._runtime is None:
            from core.runtime import RUNTIME
            self._runtime = RUNTIME
        return self._runtime

    def _on_connectivity_change(self, state: ConnectivityState) -> None:
        if state in (ConnectivityState.RECONNECTING, ConnectivityState.ONLINE):
            self.trigger_reconciliation_async()

    def trigger_reconciliation_async(self) -> None:
        threading.Thread(target=self.reconcile, daemon=True).start()

    def reconcile(self) -> Dict[str, Any]:
        with self._lock:
            if self.is_reconciling:
                return {"status": "already_reconciling"}
            self.is_reconciling = True

        try:
            rt = self.runtime
            unfrozen_count = 0
            drained_count = 0

            # 1. Unfreeze workflows paused in OFFLINE_PAUSED state
            for wf_id, wf in list(rt.workflows_store.items()):
                if wf.get("status") == "OFFLINE_PAUSED":
                    wf["status"] = "RUNNING"
                    step_name = wf.get("currentStep", "Pending step").replace("Paused at ", "")
                    wf["currentStep"] = step_name
                    wf["updatedAt"] = "now"
                    unfrozen_count += 1
                    rt._record_event(
                        CanonicalEventType.STEP_GRANTED,
                        f"Workflow {wf_id} un-frozen",
                        f"{wf['name']} resumed at {step_name} after network restoration (sunk tokens preserved)",
                        workflow_id=wf_id,
                        category="Reconciliation",
                        ui_type="success",
                    )
                    OFFLINE_JOURNAL.mark_workflow_reconciled(wf_id)

            # 2. Reconcile offline-enqueued workflows from journal
            unreconciled = OFFLINE_JOURNAL.get_unreconciled_workflows()
            if unreconciled:
                # Re-score in SunkGuard priority order: Score = base + aging * wait + beta * sunk
                def priority_key(w: Dict[str, Any]) -> float:
                    base = float(w.get("base_priority", 1.0))
                    aging = 0.35 * float(w.get("wait_ticks", 0))
                    sunk = 0.60 * (float(w.get("spent_tokens_raw", 0)) / 1000.0)
                    return base + aging + sunk

                unreconciled.sort(key=priority_key, reverse=True)

                for w in unreconciled:
                    wf_id = w.get("id")
                    if wf_id in rt.workflows_store:
                        target_wf = rt.workflows_store[wf_id]
                        if target_wf.get("status") in ("QUEUED_OFFLINE", "WAITING"):
                            target_wf["status"] = "RUNNING"
                            target_wf["updatedAt"] = "now"
                            rt._record_event(
                                CanonicalEventType.WORKFLOW_STARTED,
                                f"Admitted offline workflow {wf_id}",
                                f"{target_wf['name']} dispatched to Gemini in SunkGuard priority order",
                                workflow_id=wf_id,
                                category="Reconciliation",
                                ui_type="info",
                            )
                        drained_count += 1
                    OFFLINE_JOURNAL.mark_workflow_reconciled(wf_id)

            # Reset connectivity stats counters
            CONNECTIVITY.stats.frozen_workflows_count = 0
            CONNECTIVITY.stats.offline_queued_count = 0

            res = {
                "status": "completed",
                "unfrozen_workflows": unfrozen_count,
                "drained_offline_workflows": drained_count,
            }
            if unfrozen_count > 0 or drained_count > 0 or self.last_reconciliation_result["status"] == "none":
                self.last_reconciliation_result = res
            return res
        finally:
            with self._lock:
                self.is_reconciling = False


# Global singleton reconciler
RECONCILER = AutoReconciler()
