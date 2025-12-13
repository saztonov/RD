from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .settings import settings
from .storage import FileTaskStore, TaskStatus, task_to_dict
from .worker import process_task


app = FastAPI(title="rd-remote-ocr")

store = FileTaskStore(path=f"{settings.data_dir}/tasks.json")


class CreateTaskRequest(BaseModel):
    payload: dict


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/tasks")
def create_task(req: CreateTaskRequest) -> dict:
    task = store.create(req.payload)
    return {"id": task.id}


@app.get("/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task_to_dict(task)


@app.post("/tasks/{task_id}/run")
def run_task(task_id: str) -> dict:
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    task.status = TaskStatus.running
    store.update(task)
    process_task(store, task)
    task = store.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task_to_dict(task)


