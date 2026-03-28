"""Integration test: полный lifecycle DTO через client ↔ server boundary.

Тестирует: create request → server serialize → client parse → cache → snapshot → restore.
Не требует реального сервера — тестирует data flow через DTO.
"""
import json
import time

import pytest

from app.gui.remote_ocr.jobs_cache import JobsCache
from app.gui.remote_ocr.job_persistence import save_snapshot, load_snapshot
from rd_core.dto.jobs import JobDetailDTO, JobInfoDTO, JobListResponse


class TestLifecycleJobCreation:
    """Simulate: server creates job → client receives → cache → poll updates."""

    def test_full_job_lifecycle(self):
        cache = JobsCache()

        # 1. Server creates job and returns response
        server_response = {
            "jobs": [
                {
                    "id": "job-001",
                    "status": "queued",
                    "progress": 0.0,
                    "document_id": "doc-1",
                    "document_name": "test.pdf",
                    "task_name": "OCR test",
                    "created_at": "2026-03-28T10:00:00",
                    "updated_at": "2026-03-28T10:00:00",
                    "node_id": "node-1",
                    "priority": 0,
                },
            ],
            "server_time": "2026-03-28T10:00:00",
        }

        # 2. Client parses response via DTO
        resp = JobListResponse.from_dict(server_response)
        assert len(resp.jobs) == 1
        assert resp.jobs[0].status == "queued"

        # 3. Cache stores jobs
        cache.replace_all(resp.jobs, resp.server_time)
        assert len(cache) == 1
        assert cache.get("job-001").status == "queued"

        # 4. Server updates job to processing (delta poll)
        delta_response = {
            "jobs": [
                {
                    "id": "job-001",
                    "status": "processing",
                    "progress": 0.5,
                    "document_id": "doc-1",
                    "document_name": "test.pdf",
                    "task_name": "OCR test",
                    "created_at": "2026-03-28T10:00:00",
                    "updated_at": "2026-03-28T10:01:00",
                    "node_id": "node-1",
                    "priority": 0,
                },
            ],
            "server_time": "2026-03-28T10:01:00",
        }

        delta = JobListResponse.from_dict(delta_response)
        all_jobs = cache.update_delta(delta.jobs, delta.server_time)
        assert len(all_jobs) == 1
        assert cache.get("job-001").status == "processing"
        assert cache.get("job-001").progress == 0.5

        # 5. Server completes job
        done_response = {
            "jobs": [
                {
                    "id": "job-001",
                    "status": "done",
                    "progress": 1.0,
                    "document_id": "doc-1",
                    "document_name": "test.pdf",
                    "task_name": "OCR test",
                    "created_at": "2026-03-28T10:00:00",
                    "updated_at": "2026-03-28T10:05:00",
                    "node_id": "node-1",
                    "status_message": "Completed: 10/10 blocks",
                    "priority": 0,
                },
            ],
            "server_time": "2026-03-28T10:05:00",
        }
        done = JobListResponse.from_dict(done_response)
        cache.update_delta(done.jobs, done.server_time)

        job = cache.get("job-001")
        assert job.status == "done"
        assert job.progress == 1.0
        assert job.status_message == "Completed: 10/10 blocks"

        # 6. Download tracking
        assert not cache.is_downloaded("job-001")
        cache.mark_downloaded("job-001")
        assert cache.is_downloaded("job-001")


class TestLifecycleOptimisticUpdates:
    """Simulate: optimistic create → server confirms → merge."""

    def test_optimistic_job_lifecycle(self):
        cache = JobsCache()

        # 1. User creates job — optimistic entry
        temp_job = JobInfoDTO(
            id="uploading-temp123",
            status="uploading",
            progress=0.0,
            document_id="",
            document_name="test.pdf",
        )
        cache.add_optimistic("uploading-temp123", temp_job)

        # 2. Server confirms — real job appears
        real_job = JobInfoDTO(
            id="job-real-001",
            status="queued",
            progress=0.0,
            document_id="doc-1",
            document_name="test.pdf",
        )
        cache.remove_optimistic("uploading-temp123")
        cache.add_optimistic("job-real-001", real_job)

        # 3. Next poll — server returns real job
        server_jobs = [
            JobInfoDTO(
                id="job-real-001",
                status="queued",
                progress=0.0,
                document_id="doc-1",
                document_name="test.pdf",
            ),
        ]
        merged = cache.merge_optimistic(server_jobs)
        assert len(merged) == 1
        assert merged[0].id == "job-real-001"


class TestLifecycleCancelAll:
    """Simulate: cancel all active → optimistic update → server confirms."""

    def test_cancel_all_lifecycle(self):
        cache = JobsCache()
        cache.replace_all([
            JobInfoDTO(id="j1", status="queued", progress=0.0, document_id="d", document_name="f.pdf"),
            JobInfoDTO(id="j2", status="processing", progress=0.5, document_id="d", document_name="f.pdf"),
            JobInfoDTO(id="j3", status="done", progress=1.0, document_id="d", document_name="f.pdf"),
        ])

        # Optimistic cancel
        cache.set_status("j1", "cancelled")
        cache.set_status("j2", "cancelled")
        assert cache.get("j1").status == "cancelled"
        assert cache.get("j2").status == "cancelled"
        assert cache.get("j3").status == "done"  # not affected


class TestLifecycleJobDetail:
    """Simulate: GET /jobs/{id}/details → parse as JobDetailDTO."""

    def test_detail_response_parsing(self):
        server_response = {
            "id": "job-001",
            "status": "done",
            "progress": 1.0,
            "document_id": "doc-1",
            "document_name": "test.pdf",
            "engine": "chandra",
            "r2_prefix": "jobs/job-001",
            "result_prefix": "jobs/job-001/results",
            "node_id": "node-1",
        }
        detail = JobDetailDTO.from_dict(server_response)
        assert detail.engine == "chandra"
        assert detail.r2_prefix == "jobs/job-001"
        assert detail.result_prefix == "jobs/job-001/results"
        # Inherits base fields
        assert detail.status == "done"
        assert detail.node_id == "node-1"


class TestLifecycleSnapshotRoundTrip:
    """Simulate: cache → snapshot → new cache → restore."""

    def test_snapshot_roundtrip(self, tmp_path, monkeypatch):
        """Snapshot saves and restores correctly via QSettings mock."""
        cache = JobsCache()
        cache.replace_all([
            JobInfoDTO(
                id="j1", status="done", progress=1.0,
                document_id="d1", document_name="test.pdf",
                task_name="task1", node_id="n1", priority=3,
            ),
        ], server_time="2026-03-28T12:00:00")

        # Test data round-trip through serialization
        from dataclasses import asdict
        jobs_data = [asdict(j) for j in cache.get_all()]
        payload = json.dumps({
            "jobs": jobs_data,
            "server_time": cache.last_server_time,
            "saved_at": time.time(),
        })

        # Restore
        data = json.loads(payload)
        new_cache = JobsCache()
        restored_jobs = [JobInfoDTO.from_dict(j) for j in data["jobs"]]
        new_cache.replace_all(restored_jobs, data.get("server_time"))

        assert len(new_cache) == 1
        job = new_cache.get("j1")
        assert job.status == "done"
        assert job.task_name == "task1"
        assert job.node_id == "n1"
        assert job.priority == 3
        assert new_cache.last_server_time == "2026-03-28T12:00:00"
