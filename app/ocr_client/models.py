"""Модели данных Remote OCR клиента.

JobInfo is now an alias for the shared DTO (rd_core.dto.jobs.JobInfoDTO).
This ensures client and server use the same data contract.
"""
from rd_core.dto.jobs import JobInfoDTO

# Backward-compatible alias
JobInfo = JobInfoDTO

__all__ = ["JobInfo"]
