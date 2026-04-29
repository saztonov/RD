"""Тесты для JobsCache — thread-safe кеш задач."""
import threading
import time


from app.gui.remote_ocr.jobs_cache import JobsCache
from rd_core.dto.jobs import JobInfoDTO


def _make_job(id="j1", status="queued", **kw):
    return JobInfoDTO(
        id=id, status=status, progress=0.0,
        document_id="d1", document_name="test.pdf",
        **kw,
    )


class TestJobsCacheBasic:
    def test_empty_cache(self):
        cache = JobsCache()
        assert len(cache) == 0
        assert not cache
        assert cache.get("x") is None

    def test_replace_all(self):
        cache = JobsCache()
        jobs = [_make_job("j1"), _make_job("j2")]
        cache.replace_all(jobs, "2026-01-01")
        assert len(cache) == 2
        assert cache.last_server_time == "2026-01-01"

    def test_get(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1")])
        assert cache.get("j1").id == "j1"
        assert cache.get("missing") is None

    def test_update_delta(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1", status="queued")])

        updated = _make_job("j1", status="done")
        all_jobs = cache.update_delta([updated], "2026-01-02")
        assert len(all_jobs) == 1
        assert cache.get("j1").status == "done"
        assert cache.last_server_time == "2026-01-02"

    def test_delta_adds_new_jobs(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1")])
        cache.update_delta([_make_job("j2")])
        assert len(cache) == 2

    def test_set_status(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1", status="queued")])
        result = cache.set_status("j1", "cancelled")
        assert result.status == "cancelled"
        assert cache.get("j1").status == "cancelled"

    def test_set_status_missing(self):
        cache = JobsCache()
        assert cache.set_status("missing", "x") is None

    def test_remove(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1")])
        cache.remove("j1")
        assert len(cache) == 0

    def test_clear(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1"), _make_job("j2")])
        ids = cache.clear()
        assert set(ids) == {"j1", "j2"}
        assert len(cache) == 0

    def test_get_all_sorted(self):
        cache = JobsCache()
        cache.replace_all([
            _make_job("j2", priority=1, created_at="2026-01-02"),
            _make_job("j1", priority=0, created_at="2026-01-01"),
        ])
        sorted_jobs = cache.get_all_sorted()
        assert sorted_jobs[0].id == "j1"  # priority=0 first


class TestJobsCacheCleared:
    """cleared-set: задачи, которые пользователь явно очистил.

    Должны фильтроваться во всех write-путях (delta/full/optimistic) и
    переживать рестарт через persistence — иначе очистка списка не
    устойчива при ошибках серверного DELETE или гонке polling.
    """

    def test_clear_marks_cleared(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1"), _make_job("j2")])
        ids = cache.clear()
        assert set(ids) == {"j1", "j2"}
        assert cache.is_cleared("j1")
        assert cache.is_cleared("j2")
        assert cache.get_cleared_ids() == {"j1", "j2"}

    def test_mark_cleared_removes_from_cache(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1"), _make_job("j2"), _make_job("j3")])
        cache.mark_cleared(["j1", "j3"])
        ids = {j.id for j in cache.get_all()}
        assert ids == {"j2"}
        assert cache.is_cleared("j1") and cache.is_cleared("j3")

    def test_update_delta_filters_cleared(self):
        cache = JobsCache()
        cache.mark_cleared(["ghost"])
        cache.update_delta([_make_job("ghost", status="done"), _make_job("alive")])
        ids = {j.id for j in cache.get_all()}
        assert ids == {"alive"}
        assert cache.get("ghost") is None

    def test_replace_all_filters_cleared(self):
        cache = JobsCache()
        cache.mark_cleared(["ghost"])
        cache.replace_all([_make_job("ghost"), _make_job("alive")])
        ids = {j.id for j in cache.get_all()}
        assert ids == {"alive"}

    def test_merge_optimistic_filters_cleared(self):
        cache = JobsCache()
        cache.mark_cleared(["ghost"])
        cache.add_optimistic("ghost", _make_job("ghost", status="uploading"))
        cache.add_optimistic("temp", _make_job("temp", status="uploading"))

        merged = cache.merge_optimistic([_make_job("ghost"), _make_job("alive")])
        ids = {j.id for j in merged}
        assert "ghost" not in ids
        assert "alive" in ids and "temp" in ids

    def test_prune_cleared_drops_confirmed(self):
        cache = JobsCache()
        cache.mark_cleared(["a", "b", "c"])
        # Сервер вернул только b — значит a и c уже удалены полностью.
        cache.prune_cleared({"b"})
        assert cache.get_cleared_ids() == {"b"}

    def test_prune_cleared_empty_server(self):
        cache = JobsCache()
        cache.mark_cleared(["a", "b"])
        cache.prune_cleared(set())
        assert cache.get_cleared_ids() == set()

    def test_load_cleared_ids(self):
        cache = JobsCache()
        cache.load_cleared_ids(["x", "y"])
        assert cache.is_cleared("x") and cache.is_cleared("y")

    def test_clear_purges_optimistic_and_downloads(self):
        cache = JobsCache()
        cache.replace_all([_make_job("j1")])
        cache.add_optimistic("j1", _make_job("j1", status="uploading"))
        cache.mark_downloaded("j1")
        cache.mark_downloading("j1")
        cache.clear()
        assert not cache.is_downloaded("j1")
        assert not cache.is_downloading("j1")
        # optimistic тоже должен быть вычищен
        merged = cache.merge_optimistic([])
        assert merged == []


class TestJobsCacheOptimistic:
    def test_add_and_merge(self):
        cache = JobsCache()
        temp = _make_job("temp1", status="uploading")
        cache.add_optimistic("temp1", temp)

        server_jobs = [_make_job("j1")]
        merged = cache.merge_optimistic(server_jobs)
        assert len(merged) == 2  # j1 + temp1

    def test_merge_removes_found(self):
        cache = JobsCache()
        cache.add_optimistic("j1", _make_job("j1", status="uploading"))

        merged = cache.merge_optimistic([_make_job("j1", status="queued")])
        assert len(merged) == 1
        assert merged[0].status == "queued"

    def test_merge_removes_expired(self):
        cache = JobsCache()
        cache.add_optimistic("old", _make_job("old"))
        cache._optimistic["old"] = (cache._optimistic["old"][0], time.time() - 120)

        merged = cache.merge_optimistic([])
        assert len(merged) == 0


class TestJobsCacheDownloadTracking:
    def test_download_tracking(self):
        cache = JobsCache()
        assert not cache.is_downloaded("j1")

        cache.mark_downloaded("j1")
        assert cache.is_downloaded("j1")

    def test_downloading_guard(self):
        cache = JobsCache()
        assert not cache.is_downloading("j1")

        cache.mark_downloading("j1")
        assert cache.is_downloading("j1")

        cache.unmark_downloading("j1")
        assert not cache.is_downloading("j1")

    def test_mark_node_downloads_complete(self):
        cache = JobsCache()
        cache.replace_all([
            _make_job("j1", status="done", node_id="n1"),
            _make_job("j2", status="queued", node_id="n1"),
            _make_job("j3", status="done", node_id="n2"),
        ])
        cache.mark_node_downloads_complete("n1")
        assert cache.is_downloaded("j1")
        assert not cache.is_downloaded("j2")  # not done
        assert not cache.is_downloaded("j3")  # different node


class TestJobsCacheThreadSafety:
    def test_concurrent_updates(self):
        """Multiple threads updating cache simultaneously don't crash."""
        cache = JobsCache()
        errors = []

        def writer(thread_id):
            try:
                for i in range(100):
                    cache.replace_all([_make_job(f"j-{thread_id}-{i}")])
                    cache.get(f"j-{thread_id}-{i}")
                    cache.get_all()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread safety errors: {errors}"
