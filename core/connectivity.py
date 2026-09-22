"""Network Connectivity Manager and Circuit Breaker for SunkGuard.

Monitors outbound internet connectivity to upstream LLM APIs (Google Gemini)
and external tools. Provides:
1. Real active network probe (lightweight socket/HTTP check)
2. Software-simulated outage mode for evaluation and testing
3. State transitions: ONLINE -> DISCONNECTED -> RECONNECTING -> ONLINE
4. Subscriber callbacks on state changes
"""

from dataclasses import dataclass, field
from enum import Enum
import socket
import threading
import time
from typing import Callable, List, Optional
import urllib.request


class ConnectivityState(str, Enum):
    ONLINE = "ONLINE"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"


@dataclass
class ConnectivityStats:
    total_outages: int = 0
    total_outage_seconds: float = 0.0
    current_outage_start: Optional[float] = None
    last_reconnected_at: Optional[float] = None
    frozen_workflows_count: int = 0
    offline_queued_count: int = 0


class ConnectivityManager:
    """Manages real and simulated network availability for SunkGuard."""

    def __init__(self, probe_interval_seconds: float = 2.0):
        self.state: ConnectivityState = ConnectivityState.ONLINE
        self.simulated_outage: bool = False
        self.simulated_outage_end: float = 0.0
        self.probe_interval = probe_interval_seconds
        self.stats = ConnectivityStats()
        self._listeners: List[Callable[[ConnectivityState], None]] = []
        self._lock = threading.RLock()
        self._stop_prober = False
        self._prober_thread: Optional[threading.Thread] = None

    @property
    def is_online(self) -> bool:
        with self._lock:
            if self.simulated_outage:
                if time.time() >= self.simulated_outage_end:
                    # Simulated outage has expired, automatically restore
                    self.simulated_outage = False
                    self._set_state_locked(ConnectivityState.RECONNECTING)
                    return False
                return False
            return self.state == ConnectivityState.ONLINE

    @property
    def outage_elapsed_seconds(self) -> float:
        with self._lock:
            if self.stats.current_outage_start is None:
                return 0.0
            return max(0.0, time.time() - self.stats.current_outage_start)

    def subscribe(self, callback: Callable[[ConnectivityState], None]) -> None:
        """Register a callback for connectivity state changes."""
        with self._lock:
            self._listeners.append(callback)

    def _set_state_locked(self, new_state: ConnectivityState) -> None:
        if self.state == new_state:
            return
        prev = self.state
        self.state = new_state

        if new_state == ConnectivityState.DISCONNECTED:
            self.stats.total_outages += 1
            self.stats.current_outage_start = time.time()
        elif new_state in (ConnectivityState.RECONNECTING, ConnectivityState.ONLINE):
            if self.stats.current_outage_start is not None:
                duration = time.time() - self.stats.current_outage_start
                self.stats.total_outage_seconds += duration
                self.stats.current_outage_start = None
            self.stats.last_reconnected_at = time.time()

        # Fire callbacks in separate thread to avoid deadlocks
        callbacks = list(self._listeners)
        def notify():
            for cb in callbacks:
                try:
                    cb(new_state)
                except Exception:
                    pass
        threading.Thread(target=notify, daemon=True).start()

    def simulate_outage(self, duration_seconds: float = 60.0) -> None:
        """Triggers a software-simulated network outage for evaluation testing."""
        with self._lock:
            self.simulated_outage = True
            self.simulated_outage_end = time.time() + duration_seconds
            self._set_state_locked(ConnectivityState.DISCONNECTED)

    def restore_connectivity(self) -> None:
        """Forces immediate restoration of network connectivity."""
        with self._lock:
            self.simulated_outage = False
            self.simulated_outage_end = 0.0
            self._set_state_locked(ConnectivityState.RECONNECTING)
            # Short grace period for re-connection
            def settle():
                time.sleep(0.5)
                with self._lock:
                    if not self.simulated_outage:
                        self._set_state_locked(ConnectivityState.ONLINE)
            threading.Thread(target=settle, daemon=True).start()

    def check_real_internet(self, timeout: float = 1.5) -> bool:
        """Probes Google Gemini API host or 8.8.8.8 to check actual physical connectivity."""
        # Fast DNS / TCP socket probe to Google
        try:
            sock = socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=timeout)
            sock.close()
            return True
        except Exception:
            pass
        try:
            sock = socket.create_connection(("8.8.8.8", 53), timeout=timeout)
            sock.close()
            return True
        except Exception:
            return False

    def report_network_failure(self) -> None:
        """Called by adapters when an HTTP/socket call fails due to network outage."""
        with self._lock:
            if not self.simulated_outage and self.state == ConnectivityState.ONLINE:
                self._set_state_locked(ConnectivityState.DISCONNECTED)

    def report_network_success(self) -> None:
        """Called by adapters when an external call succeeds."""
        with self._lock:
            if not self.simulated_outage and self.state != ConnectivityState.ONLINE:
                self._set_state_locked(ConnectivityState.ONLINE)

    def start_prober(self) -> None:
        """Starts background thread probing physical connectivity."""
        if self._prober_thread and self._prober_thread.is_alive():
            return
        self._stop_prober = False
        self._prober_thread = threading.Thread(target=self._probe_loop, daemon=True)
        self._prober_thread.start()

    def stop_prober(self) -> None:
        self._stop_prober = True

    def _probe_loop(self) -> None:
        while not self._stop_prober:
            time.sleep(self.probe_interval)
            with self._lock:
                if self.simulated_outage:
                    # Check if simulated outage expired
                    if time.time() >= self.simulated_outage_end:
                        self.simulated_outage = False
                        self._set_state_locked(ConnectivityState.RECONNECTING)
                        time.sleep(0.5)
                        self._set_state_locked(ConnectivityState.ONLINE)
                    continue

            # Real probe
            online = self.check_real_internet()
            with self._lock:
                if not self.simulated_outage:
                    if online and self.state != ConnectivityState.ONLINE:
                        self._set_state_locked(ConnectivityState.ONLINE)
                    elif not online and self.state == ConnectivityState.ONLINE:
                        self._set_state_locked(ConnectivityState.DISCONNECTED)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "state": self.state.value,
                "is_online": self.is_online,
                "simulated_outage": self.simulated_outage,
                "outage_elapsed_seconds": round(self.outage_elapsed_seconds, 1),
                "total_outages": self.stats.total_outages,
                "total_outage_seconds": round(self.stats.total_outage_seconds, 1),
                "frozen_workflows": self.stats.frozen_workflows_count,
                "offline_queued": self.stats.offline_queued_count,
            }


# Global singleton instance
CONNECTIVITY = ConnectivityManager()
