"""Shared DTO models for OCR jobs API.

Used by both server (response_model) and client (response parsing).
Single source of truth for job data contracts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class JobInfoDTO:
    """Job summary for list endpoints. Shared between client and server."""

    id: str
    status: str
    progress: float
    document_id: str
    document_name: str
    task_name: str = ""
    created_at: str = ""
    updated_at: str = ""
    error_message: Optional[str] = None
    node_id: Optional[str] = None
    status_message: Optional[str] = None
    priority: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobInfoDTO:
        """Parse from API response dict."""
        return cls(
            id=data["id"],
            status=data["status"],
            progress=data["progress"],
            document_id=data["document_id"],
            document_name=data["document_name"],
            task_name=data.get("task_name", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            error_message=data.get("error_message"),
            node_id=data.get("node_id"),
            status_message=data.get("status_message"),
            priority=data.get("priority", 0),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to API response dict."""
        return asdict(self)


@dataclass
class JobDetailDTO(JobInfoDTO):
    """Extended job info for detail/single-job endpoints."""

    engine: Optional[str] = None
    r2_prefix: Optional[str] = None
    result_prefix: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobDetailDTO:
        """Parse from API response dict."""
        return cls(
            id=data["id"],
            status=data["status"],
            progress=data["progress"],
            document_id=data["document_id"],
            document_name=data["document_name"],
            task_name=data.get("task_name", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            error_message=data.get("error_message"),
            node_id=data.get("node_id"),
            status_message=data.get("status_message"),
            priority=data.get("priority", 0),
            engine=data.get("engine"),
            r2_prefix=data.get("r2_prefix"),
            result_prefix=data.get("result_prefix"),
        )


@dataclass
class JobListResponse:
    """Response from GET /jobs endpoint."""

    jobs: list[JobInfoDTO] = field(default_factory=list)
    server_time: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobListResponse:
        """Parse from API response dict."""
        return cls(
            jobs=[JobInfoDTO.from_dict(j) for j in data.get("jobs", [])],
            server_time=data.get("server_time", ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to API response dict."""
        return {
            "jobs": [j.to_dict() for j in self.jobs],
            "server_time": self.server_time,
        }
