from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class RemoteOcrClient:
    base_url: str = os.getenv("REMOTE_OCR_URL", "http://127.0.0.1:8081")

    def health(self) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            resp = client.get("/health")
            resp.raise_for_status()
            return resp.json()

    def create_task(self, payload: dict[str, Any]) -> str:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            resp = client.post("/tasks", json={"payload": payload})
            resp.raise_for_status()
            data = resp.json()
            return data["id"]

    def get_task(self, task_id: str) -> dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            resp = client.get(f"/tasks/{task_id}")
            resp.raise_for_status()
            return resp.json()


