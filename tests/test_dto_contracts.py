"""Contract tests: DTO serialization/deserialization между client и server.

Гарантируют что server response → client parsing → assert fields match.
"""
import pytest

from rd_core.dto.jobs import JobDetailDTO, JobInfoDTO, JobListResponse


class TestJobInfoDTORoundTrip:
    """Server сериализует → client десериализует — поля совпадают."""

    @pytest.fixture
    def sample_dict(self):
        """Формат dict как его возвращает server read_handlers._job_to_list_item()."""
        return {
            "id": "abc-123",
            "status": "done",
            "progress": 1.0,
            "document_id": "doc-456",
            "document_name": "test.pdf",
            "task_name": "OCR test",
            "created_at": "2026-03-28T10:00:00",
            "updated_at": "2026-03-28T10:05:00",
            "error_message": None,
            "node_id": "node-789",
            "status_message": "Completed",
            "priority": 5,
        }

    def test_from_dict_all_fields(self, sample_dict):
        job = JobInfoDTO.from_dict(sample_dict)
        assert job.id == "abc-123"
        assert job.status == "done"
        assert job.progress == 1.0
        assert job.document_id == "doc-456"
        assert job.document_name == "test.pdf"
        assert job.task_name == "OCR test"
        assert job.node_id == "node-789"
        assert job.priority == 5

    def test_to_dict_roundtrip(self, sample_dict):
        job = JobInfoDTO.from_dict(sample_dict)
        result = job.to_dict()
        assert result == sample_dict

    def test_from_dict_minimal(self):
        """Server может вернуть только обязательные поля."""
        minimal = {
            "id": "x",
            "status": "queued",
            "progress": 0.0,
            "document_id": "d",
            "document_name": "f.pdf",
        }
        job = JobInfoDTO.from_dict(minimal)
        assert job.id == "x"
        assert job.task_name == ""
        assert job.priority == 0
        assert job.error_message is None
        assert job.node_id is None

    def test_from_dict_missing_required_raises(self):
        with pytest.raises(KeyError):
            JobInfoDTO.from_dict({"id": "x"})

    def test_backward_compat_with_ocr_client_models(self):
        """app.ocr_client.models.JobInfo is now an alias for JobInfoDTO."""
        from app.ocr_client.models import JobInfo

        assert JobInfo is JobInfoDTO
        job = JobInfo(
            id="test", status="queued", progress=0.0,
            document_id="d", document_name="f.pdf",
        )
        assert isinstance(job, JobInfoDTO)


class TestJobDetailDTORoundTrip:
    def test_from_dict_with_extra_fields(self):
        data = {
            "id": "abc",
            "status": "done",
            "progress": 1.0,
            "document_id": "d1",
            "document_name": "test.pdf",
            "engine": "chandra",
            "r2_prefix": "jobs/abc",
            "result_prefix": "jobs/abc/results",
        }
        detail = JobDetailDTO.from_dict(data)
        assert detail.engine == "chandra"
        assert detail.r2_prefix == "jobs/abc"
        assert detail.result_prefix == "jobs/abc/results"

    def test_inherits_base_fields(self):
        data = {
            "id": "abc",
            "status": "processing",
            "progress": 0.5,
            "document_id": "d1",
            "document_name": "test.pdf",
            "task_name": "task1",
            "priority": 3,
        }
        detail = JobDetailDTO.from_dict(data)
        assert detail.task_name == "task1"
        assert detail.priority == 3
        assert detail.engine is None


class TestJobListResponseRoundTrip:
    def test_from_dict_with_jobs(self):
        data = {
            "jobs": [
                {
                    "id": "j1",
                    "status": "done",
                    "progress": 1.0,
                    "document_id": "d1",
                    "document_name": "a.pdf",
                },
                {
                    "id": "j2",
                    "status": "queued",
                    "progress": 0.0,
                    "document_id": "d2",
                    "document_name": "b.pdf",
                },
            ],
            "server_time": "2026-03-28T12:00:00",
        }
        resp = JobListResponse.from_dict(data)
        assert len(resp.jobs) == 2
        assert resp.jobs[0].id == "j1"
        assert resp.jobs[1].status == "queued"
        assert resp.server_time == "2026-03-28T12:00:00"

    def test_to_dict_roundtrip(self):
        resp = JobListResponse(
            jobs=[
                JobInfoDTO(
                    id="j1", status="done", progress=1.0,
                    document_id="d1", document_name="a.pdf",
                ),
            ],
            server_time="2026-03-28T12:00:00",
        )
        data = resp.to_dict()
        resp2 = JobListResponse.from_dict(data)
        assert len(resp2.jobs) == 1
        assert resp2.jobs[0].id == "j1"
        assert resp2.server_time == resp.server_time

    def test_empty_response(self):
        resp = JobListResponse.from_dict({"jobs": [], "server_time": ""})
        assert len(resp.jobs) == 0
        assert resp.server_time == ""

    def test_missing_keys_default(self):
        resp = JobListResponse.from_dict({})
        assert len(resp.jobs) == 0
        assert resp.server_time == ""
