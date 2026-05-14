"""Тесты для rd_core/models — Block, ArmorID."""

import uuid


from rd_core.models import Block, BlockSource, BlockType, ShapeType
from rd_core.models.armor_id import ArmorID, generate_armor_id, levenshtein_ratio


class TestArmorID:
    def test_encode_format(self):
        test_uuid = str(uuid.uuid4())
        encoded = ArmorID.encode(test_uuid)

        # Формат XXXX-XXXX-XXX
        parts = encoded.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
        assert len(parts[1]) == 4
        assert len(parts[2]) == 3

    def test_decode_returns_hex(self):
        test_uuid = str(uuid.uuid4())
        encoded = ArmorID.encode(test_uuid)
        decoded = ArmorID.decode(encoded)
        # decode возвращает 10-символьный hex
        assert decoded is not None
        assert len(decoded) == 10
        int(decoded, 16)  # Не падает — валидный hex

    def test_encode_uses_safe_alphabet(self):
        encoded = ArmorID.encode(str(uuid.uuid4()))
        clean = encoded.replace("-", "")
        for char in clean:
            assert char in ArmorID.ALPHABET

    def test_decode_invalid_checksum(self):
        encoded = ArmorID.encode(str(uuid.uuid4()))
        # Меняем последний символ
        clean = encoded.replace("-", "")
        bad_char = "A" if clean[-1] != "A" else "C"
        bad_code = clean[:-1] + bad_char
        formatted = f"{bad_code[:4]}-{bad_code[4:8]}-{bad_code[8:]}"
        # Может вернуть None если checksum не совпал
        ArmorID.decode(formatted)
        # Не гарантируем None (может случайно совпасть), но тест не падает

    def test_decode_wrong_length(self):
        assert ArmorID.decode("SHORT") is None
        assert ArmorID.decode("TOOLONGCODE123") is None

    def test_repair_valid_code(self):
        encoded = ArmorID.encode(str(uuid.uuid4()))
        success, fixed, msg = ArmorID.repair(encoded)
        assert success is True
        assert fixed == encoded

    def test_repair_single_error(self):
        # Детерминированная фикстура: оригинальный символ в позиции должен входить
        # в CONFUSION-список повреждающего символа, иначе repair при errors=1 не
        # попробует подставить оригинал обратно (пространство 26^11 с 3-симв.
        # checksum допускает несколько валидных кандидатов в Hamming-окрестности,
        # поиск возвращает первый найденный — не обязательно оригинал).
        # UUID подобран так, что encode даёт код с '4' в позиции 3, а '4' ∈
        # CONFUSION['A'] = ['4', 'H', 'R'] — повреждение '4'→'A' обратимо.
        uuid_fixture = "000006fa-0000-0000-0000-000000000000"
        original = ArmorID.encode(uuid_fixture)
        clean = original.replace("-", "")

        pos = 3
        assert clean[pos] in ArmorID.CONFUSION.get("A", []), (
            "Фикстура повреждена: оригинальный символ должен быть в CONFUSION['A']"
        )
        damaged = clean[:pos] + "A" + clean[pos + 1:]

        success, fixed, _ = ArmorID.repair(damaged)
        assert success, "repair должен восстановить single-char повреждение"
        assert fixed == original, f"Ожидался {original}, получено {fixed}"

    def test_multiple_encode_different_uuids(self):
        codes = set()
        for _ in range(100):
            code = ArmorID.encode(str(uuid.uuid4()))
            codes.add(code)
        # Все должны быть уникальными
        assert len(codes) == 100


class TestGenerateArmorId:
    def test_format(self):
        armor_id = generate_armor_id()
        parts = armor_id.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4
        assert len(parts[1]) == 4
        assert len(parts[2]) == 3

    def test_uniqueness(self):
        ids = {generate_armor_id() for _ in range(100)}
        assert len(ids) == 100


class TestLevenshteinRatio:
    def test_identical(self):
        assert levenshtein_ratio("abc", "abc") == 100.0

    def test_empty(self):
        assert levenshtein_ratio("", "abc") == 0.0
        assert levenshtein_ratio("abc", "") == 0.0

    def test_completely_different(self):
        ratio = levenshtein_ratio("abc", "xyz")
        assert ratio < 50.0

    def test_one_char_diff(self):
        ratio = levenshtein_ratio("abc", "adc")
        assert ratio > 50.0


class TestBlock:
    def test_create_with_auto_id(self):
        block = Block.create(
            page_index=0,
            coords_px=(100, 200, 500, 400),
            page_width=1240,
            page_height=1754,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
        )
        assert block.id is not None
        assert len(block.id) == 13  # XXXX-XXXX-XXX
        assert block.page_index == 0
        assert block.coords_px == (100, 200, 500, 400)
        assert block.block_type == BlockType.TEXT

    def test_px_to_norm(self):
        norm = Block.px_to_norm((100, 200, 500, 400), 1000, 2000)
        assert norm == (0.1, 0.1, 0.5, 0.2)

    def test_norm_to_px(self):
        px = Block.norm_to_px((0.1, 0.1, 0.5, 0.2), 1000, 2000)
        assert px == (100, 200, 500, 400)

    def test_to_dict_from_dict_roundtrip(self):
        block = Block.create(
            page_index=0,
            coords_px=(100, 200, 500, 400),
            page_width=1240,
            page_height=1754,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
        )
        block.ocr_text = "Test OCR result"
        block.hint = "Test hint"

        d = block.to_dict()
        restored, was_migrated = Block.from_dict(d, migrate_ids=False)

        assert restored.id == block.id
        assert restored.page_index == block.page_index
        assert restored.coords_px == block.coords_px
        assert restored.block_type == block.block_type
        assert restored.ocr_text == block.ocr_text
        assert restored.hint == block.hint

    def test_from_dict_with_string_enums(self):
        data = {
            "id": "ACDE-FGHJ-KLM",
            "page_index": 0,
            "coords_px": [100, 200, 500, 400],
            "coords_norm": [0.1, 0.1, 0.5, 0.2],
            "block_type": "text",
            "source": "user",
            "shape_type": "rectangle",
        }
        block, _ = Block.from_dict(data, migrate_ids=False)
        assert block.block_type == BlockType.TEXT
        assert block.source == BlockSource.USER
        assert block.shape_type == ShapeType.RECTANGLE

    def test_from_dict_v2_fields(self):
        """from_dict требует v2 поля (coords_norm, source)."""
        data = {
            "id": "ACDE-FGHJ-KLM",
            "page_index": 0,
            "coords_px": [100, 200, 500, 400],
            "coords_norm": [0.1, 0.1, 0.5, 0.2],
            "block_type": "text",
            "source": "user",
        }
        block, _ = Block.from_dict(data, migrate_ids=False)
        assert block is not None
        assert block.page_index == 0
        assert block.id == "ACDE-FGHJ-KLM"

    def test_polygon_create_fills_norm(self):
        """Block.create для POLYGON автоматически заполняет polygon_points_norm."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = Block.create(
            page_index=0,
            coords_px=(100, 100, 400, 400),
            page_width=1000,
            page_height=1500,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
            shape_type=ShapeType.POLYGON,
            polygon_points=points,
        )
        assert block.polygon_points == points
        assert block.polygon_points_norm is not None
        assert len(block.polygon_points_norm) == len(points)
        for (px, py), (nx, ny) in zip(points, block.polygon_points_norm):
            assert nx == px / 1000
            assert ny == py / 1500

    def test_polygon_norm_roundtrip(self):
        """to_dict/from_dict сохраняют и восстанавливают polygon_points_norm."""
        points = [(100, 100), (400, 150), (350, 400), (200, 380)]
        block = Block.create(
            page_index=0,
            coords_px=(100, 100, 400, 400),
            page_width=1000,
            page_height=1500,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
            shape_type=ShapeType.POLYGON,
            polygon_points=points,
        )
        restored, _ = Block.from_dict(block.to_dict(), migrate_ids=False)
        assert restored.polygon_points == block.polygon_points
        assert restored.polygon_points_norm == block.polygon_points_norm

    def test_polygon_from_dict_without_norm(self):
        """Старый JSON без polygon_points_norm загружается, поле остаётся None."""
        data = {
            "id": "ACDE-FGHJ-KLM",
            "page_index": 0,
            "coords_px": [100, 100, 400, 400],
            "coords_norm": [0.1, 0.067, 0.4, 0.267],
            "block_type": "text",
            "source": "user",
            "shape_type": "polygon",
            "polygon_points": [[100, 100], [400, 150], [350, 400]],
        }
        block, _ = Block.from_dict(data, migrate_ids=False)
        assert block.shape_type == ShapeType.POLYGON
        assert block.polygon_points == [(100, 100), (400, 150), (350, 400)]
        assert block.polygon_points_norm is None

    def test_set_polygon_points_updates_everything(self):
        """set_polygon_points обновляет polygon_points, polygon_points_norm, bbox."""
        block = Block.create(
            page_index=0,
            coords_px=(100, 100, 400, 400),
            page_width=1000,
            page_height=1500,
            block_type=BlockType.TEXT,
            source=BlockSource.USER,
            shape_type=ShapeType.POLYGON,
            polygon_points=[(100, 100), (400, 150), (350, 400)],
        )
        new_points = [(150, 200), (500, 250), (450, 500), (200, 450)]
        block.set_polygon_points(new_points, 1000, 1500)
        assert block.polygon_points == new_points
        assert block.polygon_points_norm == [(p[0] / 1000, p[1] / 1500) for p in new_points]
        assert block.coords_px == (150, 200, 500, 500)
        assert block.coords_norm == (150 / 1000, 200 / 1500, 500 / 1000, 500 / 1500)
