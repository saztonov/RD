"""Утилиты для работы со строками."""


def levenshtein_ratio(s1: str, s2: str) -> float:
    """
    Вычислить схожесть двух строк (0-100%) на основе расстояния Левенштейна.
    Устойчиво к вставкам/удалениям символов (OCR-ошибки).
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 100.0

    len1, len2 = len(s1), len(s2)

    # Матрица расстояний (оптимизация памяти - только 2 строки)
    prev = list(range(len2 + 1))
    curr = [0] * (len2 + 1)

    for i in range(1, len1 + 1):
        curr[0] = i
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,  # удаление
                curr[j - 1] + 1,  # вставка
                prev[j - 1] + cost,  # замена
            )
        prev, curr = curr, prev

    distance = prev[len2]
    max_len = max(len1, len2)
    return ((max_len - distance) / max_len) * 100
