"""Тесты для needs_model_reload — корректное поведение при отсутствующем
context_length в ответе LM Studio API.

Регрессия: при ctx=None ранее возвращалось (True, ...) — false positive,
который форсил reload модели и вызывал гонку "model unloaded mid-request"
с параллельными задачами в продакшн-логе 2026-04-28.
"""

from rd_core.ocr._chandra_common import needs_model_reload


def test_no_loaded_instances_means_reload():
    need, reason = needs_model_reload([], required_context=36601)
    assert need is True
    assert "не загружена" in reason


def test_matching_context_length_no_reload():
    instances = [{"id": "inst-1", "context_length": 36601}]
    need, reason = needs_model_reload(instances, required_context=36601)
    assert need is False
    assert "OK" in reason


def test_missing_context_length_assumes_ok():
    """LM Studio в некоторых версиях не возвращает context_length —
    это НЕ повод выгружать и перезагружать модель."""
    instances = [{"id": "inst-1"}]  # ctx отсутствует
    need, reason = needs_model_reload(instances, required_context=36601)
    assert need is False, "При ctx=None модель должна считаться загруженной OK"
    assert "OK" in reason


def test_explicit_none_context_length_assumes_ok():
    instances = [{"id": "inst-1", "context_length": None}]
    need, reason = needs_model_reload(instances, required_context=36601)
    assert need is False


def test_mismatched_context_length_forces_reload():
    instances = [{"id": "inst-1", "context_length": 8192}]
    need, reason = needs_model_reload(instances, required_context=36601)
    assert need is True
    assert "8192" in reason


def test_multiple_instances_one_mismatched():
    instances = [
        {"id": "inst-1", "context_length": 36601},
        {"id": "inst-2", "context_length": 8192},
    ]
    need, reason = needs_model_reload(instances, required_context=36601)
    assert need is True
    assert "inst-2" in reason


def test_multiple_instances_one_missing_context():
    """Mixed: один инстанс с ctx=None (assume OK), другой OK → no reload."""
    instances = [
        {"id": "inst-1"},
        {"id": "inst-2", "context_length": 36601},
    ]
    need, reason = needs_model_reload(instances, required_context=36601)
    assert need is False
