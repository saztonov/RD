"""Router для задач OCR"""
from fastapi import APIRouter

from apps.remote_ocr_server.routes.jobs.confirm_handler import confirm_job_handler
from apps.remote_ocr_server.routes.jobs.create_handler import create_job_handler
from apps.remote_ocr_server.routes.jobs.delete_handler import delete_job_handler
from apps.remote_ocr_server.routes.jobs.init_handler import init_job_handler
from apps.remote_ocr_server.routes.jobs.read_handlers import (
    download_result_handler,
    get_job_details_handler,
    get_job_handler,
    get_job_progress_handler,
    get_jobs_changes_handler,
    list_jobs_handler,
)
from apps.remote_ocr_server.routes.jobs.update_handlers import (
    cancel_job_handler,
    restart_job_handler,
    start_job_handler,
    update_job_handler,
)

router = APIRouter(prefix="/jobs", tags=["jobs"])

# POST endpoints - Direct upload (v2)
router.post("/init")(init_job_handler)
router.post("/{job_id}/confirm")(confirm_job_handler)

# POST endpoints - Legacy upload (v1)
router.post("")(create_job_handler)
router.post("/{job_id}/restart")(restart_job_handler)
router.post("/{job_id}/start")(start_job_handler)
router.post("/{job_id}/cancel")(cancel_job_handler)

# GET endpoints
router.get("")(list_jobs_handler)
router.get("/changes")(get_jobs_changes_handler)
router.get("/{job_id}")(get_job_handler)
router.get("/{job_id}/details")(get_job_details_handler)
router.get("/{job_id}/progress")(get_job_progress_handler)
router.get("/{job_id}/result")(download_result_handler)

# PATCH endpoints
router.patch("/{job_id}")(update_job_handler)

# DELETE endpoints
router.delete("/{job_id}")(delete_job_handler)
