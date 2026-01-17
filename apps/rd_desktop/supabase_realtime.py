"""Supabase Realtime client for job status updates.

Uses PySide6 QtWebSockets for WebSocket connection.
Subscribes to changes on the `jobs` table and emits Qt signals.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

logger = logging.getLogger(__name__)


class RealtimeConnectionState(Enum):
    """Connection state for Realtime client."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


class SupabaseRealtimeClient(QObject):
    """
    Supabase Realtime client using Phoenix WebSocket protocol.

    Subscribes to Postgres changes on specified tables and emits
    Qt signals when changes are received.

    Usage:
        client = SupabaseRealtimeClient()
        client.job_changed.connect(on_job_changed)
        client.subscribe_to_jobs()
        client.connect_to_realtime()
    """

    # Signals
    connected = Signal()
    disconnected = Signal()
    connection_error = Signal(str)
    job_changed = Signal(dict)  # Emits job data on INSERT/UPDATE/DELETE
    state_changed = Signal(str)  # Emits new state name

    # Phoenix protocol constants
    HEARTBEAT_INTERVAL = 30000  # 30 seconds
    RECONNECT_DELAY_INITIAL = 1000  # 1 second
    RECONNECT_DELAY_MAX = 30000  # 30 seconds

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._supabase_url = os.getenv("SUPABASE_URL", "")
        self._supabase_key = os.getenv("SUPABASE_KEY", "")

        self._websocket = QWebSocket()
        self._websocket.connected.connect(self._on_connected)
        self._websocket.disconnected.connect(self._on_disconnected)
        self._websocket.textMessageReceived.connect(self._on_message)
        self._websocket.errorOccurred.connect(self._on_error)

        self._state = RealtimeConnectionState.DISCONNECTED
        self._ref = 0
        self._subscriptions: Dict[str, str] = {}  # topic -> subscription_id
        self._pending_subscriptions: List[str] = []

        # Heartbeat timer
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)

        # Reconnect timer
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._try_reconnect)
        self._reconnect_delay = self.RECONNECT_DELAY_INITIAL
        self._reconnect_attempts = 0

        self._should_reconnect = False

    @property
    def state(self) -> RealtimeConnectionState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state == RealtimeConnectionState.CONNECTED

    def _set_state(self, new_state: RealtimeConnectionState):
        if self._state != new_state:
            self._state = new_state
            self.state_changed.emit(new_state.value)
            logger.debug(f"Realtime state changed: {new_state.value}")

    def _get_next_ref(self) -> str:
        self._ref += 1
        return str(self._ref)

    def _get_realtime_url(self) -> str:
        """Build Supabase Realtime WebSocket URL."""
        if not self._supabase_url:
            raise ValueError("SUPABASE_URL not set")

        # Convert REST URL to Realtime URL
        # https://xxx.supabase.co -> wss://xxx.supabase.co/realtime/v1/websocket
        base_url = self._supabase_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base_url}/realtime/v1/websocket?apikey={self._supabase_key}&vsn=1.0.0"

    def connect_to_realtime(self):
        """Connect to Supabase Realtime WebSocket."""
        if self._state in (RealtimeConnectionState.CONNECTING, RealtimeConnectionState.CONNECTED):
            logger.debug("Already connecting/connected")
            return

        if not self._supabase_url or not self._supabase_key:
            logger.warning("Supabase credentials not set, cannot connect to Realtime")
            self.connection_error.emit("Supabase credentials not set")
            return

        try:
            url = self._get_realtime_url()
            logger.info(f"Connecting to Supabase Realtime...")
            self._set_state(RealtimeConnectionState.CONNECTING)
            self._should_reconnect = True
            self._websocket.open(url)
        except Exception as e:
            logger.error(f"Failed to connect to Realtime: {e}")
            self._set_state(RealtimeConnectionState.DISCONNECTED)
            self.connection_error.emit(str(e))

    def disconnect(self):
        """Disconnect from Realtime."""
        self._should_reconnect = False
        self._reconnect_timer.stop()
        self._heartbeat_timer.stop()

        if self._websocket.state() != QAbstractSocket.SocketState.UnconnectedState:
            self._websocket.close()

        self._subscriptions.clear()
        self._set_state(RealtimeConnectionState.DISCONNECTED)
        logger.info("Disconnected from Supabase Realtime")

    def subscribe_to_jobs(self, client_id: Optional[str] = None):
        """
        Subscribe to changes on the jobs table.

        Args:
            client_id: Optional filter by client_id (RLS-aware)
        """
        topic = "realtime:public:jobs"
        if topic in self._subscriptions:
            logger.debug(f"Already subscribed to {topic}")
            return

        if self._state == RealtimeConnectionState.CONNECTED:
            self._send_subscription(topic)
        else:
            self._pending_subscriptions.append(topic)
            logger.debug(f"Queued subscription to {topic}")

    def _send_subscription(self, topic: str):
        """Send subscription message for a topic."""
        ref = self._get_next_ref()
        message = {
            "topic": topic,
            "event": "phx_join",
            "payload": {
                "config": {
                    "broadcast": {"self": False},
                    "presence": {"key": ""},
                    "postgres_changes": [
                        {
                            "event": "*",  # INSERT, UPDATE, DELETE
                            "schema": "public",
                            "table": "jobs",
                        }
                    ]
                }
            },
            "ref": ref,
        }

        self._send_message(message)
        self._subscriptions[topic] = ref
        logger.info(f"Subscribed to {topic}")

    def _send_message(self, message: dict):
        """Send JSON message over WebSocket."""
        if self._websocket.state() == QAbstractSocket.SocketState.ConnectedState:
            text = json.dumps(message)
            self._websocket.sendTextMessage(text)
            logger.debug(f"Sent: {message.get('event', 'unknown')} to {message.get('topic', 'unknown')}")

    def _send_heartbeat(self):
        """Send Phoenix heartbeat to keep connection alive."""
        message = {
            "topic": "phoenix",
            "event": "heartbeat",
            "payload": {},
            "ref": self._get_next_ref(),
        }
        self._send_message(message)

    @Slot()
    def _on_connected(self):
        """Handle WebSocket connected."""
        logger.info("Connected to Supabase Realtime")
        self._set_state(RealtimeConnectionState.CONNECTED)
        self._reconnect_delay = self.RECONNECT_DELAY_INITIAL
        self._reconnect_attempts = 0

        # Start heartbeat
        self._heartbeat_timer.start(self.HEARTBEAT_INTERVAL)

        # Send pending subscriptions
        for topic in self._pending_subscriptions:
            self._send_subscription(topic)
        self._pending_subscriptions.clear()

        self.connected.emit()

    @Slot()
    def _on_disconnected(self):
        """Handle WebSocket disconnected."""
        logger.warning("Disconnected from Supabase Realtime")
        self._heartbeat_timer.stop()

        if self._should_reconnect:
            self._set_state(RealtimeConnectionState.RECONNECTING)
            self._schedule_reconnect()
        else:
            self._set_state(RealtimeConnectionState.DISCONNECTED)

        self.disconnected.emit()

    @Slot(str)
    def _on_message(self, text: str):
        """Handle incoming WebSocket message."""
        try:
            message = json.loads(text)
            event = message.get("event")
            topic = message.get("topic")
            payload = message.get("payload", {})

            logger.debug(f"Received: {event} from {topic}")

            if event == "phx_reply":
                # Subscription confirmation
                status = payload.get("status")
                if status == "ok":
                    logger.debug(f"Subscription confirmed for {topic}")
                else:
                    logger.warning(f"Subscription failed for {topic}: {payload}")

            elif event == "postgres_changes":
                # Database change event
                self._handle_postgres_change(payload)

            elif event == "phx_error":
                logger.error(f"Phoenix error: {payload}")

            elif event == "phx_close":
                logger.info(f"Channel closed: {topic}")
                self._subscriptions.pop(topic, None)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse message: {e}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def _handle_postgres_change(self, payload: dict):
        """Handle Postgres change notification."""
        data = payload.get("data", {})

        # Extract change type and record
        change_type = data.get("type")  # INSERT, UPDATE, DELETE
        table = data.get("table")
        schema = data.get("schema")
        record = data.get("record", {})
        old_record = data.get("old_record", {})

        if table != "jobs":
            return

        logger.info(f"Job change: {change_type} - {record.get('id', 'unknown')[:8]}...")

        # Emit signal with job data
        job_data = {
            "type": change_type,
            "record": record,
            "old_record": old_record,
        }
        self.job_changed.emit(job_data)

    @Slot()
    def _on_error(self):
        """Handle WebSocket error."""
        error = self._websocket.errorString()
        logger.error(f"WebSocket error: {error}")
        self.connection_error.emit(error)

    def _schedule_reconnect(self):
        """Schedule reconnection with exponential backoff."""
        self._reconnect_attempts += 1
        delay = min(
            self._reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
            self.RECONNECT_DELAY_MAX
        )

        logger.info(f"Scheduling reconnect in {delay}ms (attempt {self._reconnect_attempts})")
        self._reconnect_timer.start(int(delay))

    @Slot()
    def _try_reconnect(self):
        """Attempt to reconnect."""
        if not self._should_reconnect:
            return

        logger.info("Attempting to reconnect to Realtime...")

        # Re-queue subscriptions
        self._pending_subscriptions = list(self._subscriptions.keys())
        self._subscriptions.clear()

        try:
            url = self._get_realtime_url()
            self._websocket.open(url)
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            self._schedule_reconnect()


class RealtimeJobMonitor(QObject):
    """
    High-level job monitor using Supabase Realtime.

    Combines Realtime updates with fallback to HTTP polling.
    Emits unified signals for job changes regardless of source.
    """

    # Unified signals
    jobs_updated = Signal(list)  # Full job list
    job_changed = Signal(object)  # Single job change (JobInfo)
    connection_status = Signal(str)  # "realtime", "polling", "disconnected"

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)

        self._realtime_client = SupabaseRealtimeClient(self)
        self._realtime_client.connected.connect(self._on_realtime_connected)
        self._realtime_client.disconnected.connect(self._on_realtime_disconnected)
        self._realtime_client.job_changed.connect(self._on_realtime_job_changed)
        self._realtime_client.connection_error.connect(self._on_realtime_error)

        self._use_realtime = True
        self._is_realtime_connected = False

        # Job cache for merging updates
        self._jobs_cache: Dict[str, Any] = {}

    @property
    def realtime_client(self) -> SupabaseRealtimeClient:
        return self._realtime_client

    @property
    def is_realtime_connected(self) -> bool:
        return self._is_realtime_connected

    def start(self):
        """Start monitoring jobs via Realtime."""
        if self._use_realtime:
            self._realtime_client.subscribe_to_jobs()
            self._realtime_client.connect_to_realtime()

    def stop(self):
        """Stop monitoring."""
        self._realtime_client.disconnect()

    def set_use_realtime(self, enabled: bool):
        """Enable/disable Realtime (for fallback to polling)."""
        self._use_realtime = enabled
        if not enabled:
            self._realtime_client.disconnect()

    def update_job_cache(self, jobs: list):
        """Update local job cache (called after HTTP fetch)."""
        self._jobs_cache = {j.id if hasattr(j, 'id') else j['id']: j for j in jobs}

    @Slot()
    def _on_realtime_connected(self):
        self._is_realtime_connected = True
        self.connection_status.emit("realtime")
        logger.info("Job monitor: Realtime connected")

    @Slot()
    def _on_realtime_disconnected(self):
        self._is_realtime_connected = False
        self.connection_status.emit("polling")
        logger.info("Job monitor: Realtime disconnected, falling back to polling")

    @Slot(dict)
    def _on_realtime_job_changed(self, data: dict):
        """Handle job change from Realtime."""
        from apps.rd_desktop.ocr_client.models import JobInfo

        change_type = data.get("type")
        record = data.get("record", {})

        if change_type == "DELETE":
            job_id = data.get("old_record", {}).get("id")
            if job_id and job_id in self._jobs_cache:
                del self._jobs_cache[job_id]
                logger.debug(f"Job {job_id[:8]}... deleted from cache")
        else:
            # INSERT or UPDATE
            try:
                job_info = JobInfo(
                    id=record.get("id", ""),
                    status=record.get("status", ""),
                    progress=record.get("progress", 0.0),
                    document_id=record.get("document_id", ""),
                    document_name=record.get("document_name", ""),
                    task_name=record.get("task_name", ""),
                    created_at=record.get("created_at", ""),
                    updated_at=record.get("updated_at", ""),
                    error_message=record.get("error_message"),
                    node_id=record.get("node_id"),
                    status_message=record.get("status_message"),
                )
                self._jobs_cache[job_info.id] = job_info
                self.job_changed.emit(job_info)
                logger.debug(f"Job {job_info.id[:8]}... updated via Realtime")
            except Exception as e:
                logger.error(f"Failed to parse job from Realtime: {e}")

        # Emit full list
        all_jobs = list(self._jobs_cache.values())
        all_jobs.sort(key=lambda j: getattr(j, 'created_at', '') or '', reverse=True)
        self.jobs_updated.emit(all_jobs)

    @Slot(str)
    def _on_realtime_error(self, error: str):
        logger.warning(f"Realtime error: {error}")
        self.connection_status.emit("polling")
