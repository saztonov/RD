"""
ArmorID - OCR-resistant block identifier encoding/decoding.

ArmorID uses a 26-character alphabet resistant to OCR errors and includes
checksum for validation and error correction.

Format: XXXX-XXXX-XXX (8 payload + 3 checksum)
"""

import itertools
import secrets
from typing import List, Optional, Tuple


class ArmorID:
    """
    Encode/decode UUID to short OCR-resistant code XXXX-XXXX-XXX.

    - Uses 26-character alphabet resistant to OCR errors
    - 8 characters payload (encodes first 10 hex digits of UUID)
    - 3 characters checksum for recovery
    """

    # Safe alphabet (26 characters) - no visually similar chars
    ALPHABET = "34679ACDEFGHJKLMNPQRTUVWXY"

    # Character -> index mapping
    CHAR_MAP = {char: idx for idx, char in enumerate(ALPHABET)}

    # OCR visual confusion matrix
    CONFUSION = {
        "0": ["O", "D", "Q", "C"],
        "1": ["L", "T", "J"],
        "2": ["Z", "7"],
        "5": ["S", "6"],
        "8": ["B", "3", "6", "9"],
        "Z": ["2", "7"],
        "B": ["8", "3", "6", "E", "R"],
        "S": ["5", "6"],
        "O": ["0", "D", "Q"],
        "I": ["1", "L", "T"],
        # Internal confusions
        "3": ["8", "9", "E"],
        "4": ["A", "H"],
        "6": ["G", "8", "5"],
        "7": ["T", "2", "Y"],
        "9": ["P", "8", "6"],
        "A": ["4", "H", "R"],
        "D": ["0", "O", "Q"],
        "E": ["F", "3", "B"],
        "F": ["E", "P"],
        "G": ["6", "C", "Q"],
        "H": ["A", "4", "M", "N"],
        "K": ["X", "R"],
        "M": ["N", "H", "W"],
        "N": ["M", "H"],
        "P": ["R", "F", "9"],
        "Q": ["0", "O", "D"],
        "R": ["P", "K", "A"],
        "T": ["7", "Y", "1"],
        "U": ["V", "W"],
        "V": ["U", "Y"],
        "W": ["M", "V"],
        "X": ["K", "Y"],
        "Y": ["V", "T", "7"],
    }

    @classmethod
    def generate(cls) -> str:
        """
        Generate unique block ID in format XXXX-XXXX-XXX.

        40 bits entropy (8 characters payload) + 3 characters checksum.
        """
        # 40 bits = 5 bytes
        random_bytes = secrets.token_bytes(5)
        num = int.from_bytes(random_bytes, "big")

        payload = cls._num_to_base26(num, 8)
        checksum = cls._calculate_checksum(payload)
        full_code = payload + checksum
        return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"

    @classmethod
    def encode(cls, uuid_str: str) -> str:
        """
        Encode UUID to format XXXX-XXXX-XXX.
        Uses first 10 hex characters of UUID (40 bits).
        """
        # Clean UUID from dashes
        clean = uuid_str.replace("-", "").lower()

        # Take first 10 hex characters (40 bits)
        hex_prefix = clean[:10]

        # Convert to number
        num = int(hex_prefix, 16)

        # Encode to base26 (8 characters sufficient for 40 bits)
        payload = cls._num_to_base26(num, 8)

        # Calculate checksum (3 characters)
        checksum = cls._calculate_checksum(payload)

        full_code = payload + checksum
        return f"{full_code[:4]}-{full_code[4:8]}-{full_code[8:]}"

    @classmethod
    def decode(cls, armor_code: str) -> Optional[str]:
        """
        Decode armor code back to hex prefix (10 characters).
        Returns None if code is invalid.
        """
        clean = armor_code.replace("-", "").replace(" ", "").upper()

        if len(clean) != 11:
            return None

        payload = clean[:8]
        checksum = clean[8:]

        # Verify checksum
        if checksum != cls._calculate_checksum(payload):
            return None

        # Decode payload to number
        try:
            num = cls._base26_to_num(payload)
        except (KeyError, ValueError):
            return None

        # Convert to hex (10 characters with leading zeros)
        return f"{num:010x}"

    @classmethod
    def repair(cls, input_code: str) -> Tuple[bool, Optional[str], str]:
        """
        Repair damaged code (up to 3 errors).
        Supports codes 10-12 characters (OCR may add/remove chars).
        Returns: (success, fixed_code, message)
        """
        clean = input_code.replace("-", "").replace(" ", "").upper()

        # Check directly
        if cls._is_valid(clean):
            formatted = f"{clean[:4]}-{clean[4:8]}-{clean[8:]}"
            return True, formatted, "Code is correct"

        # Shortened code (10 chars) - try inserting character at each position
        if len(clean) == 10:
            for pos in range(11):  # 11 positions for insertion
                for char in cls.ALPHABET:
                    candidate = clean[:pos] + char + clean[pos:]
                    if cls._is_valid(candidate):
                        formatted = f"{candidate[:4]}-{candidate[4:8]}-{candidate[8:]}"
                        return True, formatted, "Restored missing character"

        # Lengthened code (12 chars) - try removing extra char
        if len(clean) == 12:
            for i in range(12):
                candidate = clean[:i] + clean[i + 1 :]
                if cls._is_valid(candidate):
                    formatted = f"{candidate[:4]}-{candidate[4:8]}-{candidate[8:]}"
                    return True, formatted, "Removed extra character"

        # Build candidates for each position
        candidates_per_pos = []
        for char in clean:
            options = [char] if char in cls.ALPHABET else []

            # Add visual doubles
            if char in cls.CONFUSION:
                options.extend([c for c in cls.CONFUSION[char] if c in cls.ALPHABET])

            # If garbage character - add whole alphabet
            if not options:
                options = list(cls.ALPHABET)
            else:
                options = list(set(options))

            candidates_per_pos.append(options)

        original = list(clean)

        # Try 1, 2, 3 errors
        for errors in range(1, 4):
            for positions in itertools.combinations(range(len(clean)), errors):
                substitutions = []
                for pos in positions:
                    opts = [c for c in candidates_per_pos[pos] if c != original[pos]]
                    if opts:
                        substitutions.append(opts)
                    else:
                        substitutions.append(candidates_per_pos[pos])

                for sub in itertools.product(*substitutions):
                    temp = list(original)
                    for idx, char_idx in enumerate(positions):
                        temp[char_idx] = sub[idx]

                    candidate = "".join(temp)
                    if cls._is_valid(candidate):
                        formatted = f"{candidate[:4]}-{candidate[4:8]}-{candidate[8:]}"
                        return True, formatted, f"Restored {errors} error(s)"

        return False, None, "Could not restore"

    @classmethod
    def match_to_uuid(
        cls, armor_code: str, expected_uuids: List[str], score_cutoff: float = 70.0
    ) -> Tuple[Optional[str], float]:
        """
        Match armor code to expected IDs (UUID or armor ID).
        Uses fuzzy search if exact/repaired match not found.
        Returns: (matched_id, score)
        """
        input_clean = armor_code.replace("-", "").replace(" ", "").upper()

        # 1. Try to repair code via repair()
        success, fixed, _ = cls.repair(armor_code)

        if success and fixed:
            fixed_clean = fixed.replace("-", "").upper()

            # Direct match with armor ID
            for expected in expected_uuids:
                expected_clean = expected.replace("-", "").upper()
                if len(expected_clean) == 11 and all(
                    c in cls.ALPHABET for c in expected_clean
                ):
                    if expected_clean == fixed_clean:
                        return expected, 100.0

            # Legacy: decode to hex prefix and search UUID
            hex_prefix = cls.decode(fixed)
            if hex_prefix:
                for uuid in expected_uuids:
                    clean_uuid = uuid.replace("-", "").lower()
                    if len(clean_uuid) == 32 and all(
                        c in "0123456789abcdef" for c in clean_uuid
                    ):
                        if clean_uuid.startswith(hex_prefix):
                            return uuid, 100.0

        # 2. If repair didn't help - use fuzzy search (Levenshtein)
        best_match = None
        best_score = 0.0

        for expected in expected_uuids:
            expected_clean = expected.replace("-", "").upper()

            # Only armor ID (11 chars)
            if len(expected_clean) != 11:
                continue
            if not all(c in cls.ALPHABET for c in expected_clean):
                continue

            # Compare cleaned codes
            score = cls._levenshtein_ratio(input_clean, expected_clean)

            if score > best_score:
                best_score = score
                best_match = expected

        if best_match and best_score >= score_cutoff:
            return best_match, best_score

        return None, 0.0

    @classmethod
    def is_valid(cls, block_id: str) -> bool:
        """Check if ID is armor format (XXXX-XXXX-XXX) with valid checksum."""
        clean = block_id.replace("-", "").replace(" ", "").upper()
        return cls._is_valid(clean)

    @classmethod
    def _levenshtein_ratio(cls, s1: str, s2: str) -> float:
        """
        Calculate similarity of two strings (0-100%) based on Levenshtein distance.
        """
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 100.0

        len1, len2 = len(s1), len(s2)

        # Distance matrix (memory optimization - only 2 rows)
        prev = list(range(len2 + 1))
        curr = [0] * (len2 + 1)

        for i in range(1, len1 + 1):
            curr[0] = i
            for j in range(1, len2 + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                curr[j] = min(
                    prev[j] + 1,  # deletion
                    curr[j - 1] + 1,  # insertion
                    prev[j - 1] + cost,  # substitution
                )
            prev, curr = curr, prev

        distance = prev[len2]
        max_len = max(len1, len2)
        return ((max_len - distance) / max_len) * 100

    @classmethod
    def _num_to_base26(cls, num: int, length: int) -> str:
        """Convert number to base26 string of fixed length."""
        if num == 0:
            return cls.ALPHABET[0] * length

        result = []
        while num > 0:
            result.append(cls.ALPHABET[num % 26])
            num //= 26

        # Pad to required length
        while len(result) < length:
            result.append(cls.ALPHABET[0])

        return "".join(reversed(result[-length:]))

    @classmethod
    def _base26_to_num(cls, s: str) -> int:
        """Convert base26 string to number."""
        num = 0
        for char in s:
            num = num * 26 + cls.CHAR_MAP[char]
        return num

    @classmethod
    def _calculate_checksum(cls, payload: str) -> str:
        """Calculate 3-character checksum."""
        v1, v2, v3 = 0, 0, 0
        for i, char in enumerate(payload):
            val = cls.CHAR_MAP.get(char, 0)
            v1 += val
            v2 += val * (i + 3)
            v3 += val * (i + 7) * (i + 1)

        return cls.ALPHABET[v1 % 26] + cls.ALPHABET[v2 % 26] + cls.ALPHABET[v3 % 26]

    @classmethod
    def _is_valid(cls, code: str) -> bool:
        """Check code validity (11 chars: 8 payload + 3 checksum)."""
        if len(code) != 11:
            return False

        # All characters must be in alphabet
        if not all(c in cls.ALPHABET for c in code):
            return False

        payload = code[:8]
        checksum = code[8:]
        return checksum == cls._calculate_checksum(payload)


# Convenience functions for backward compatibility


def generate_armor_id() -> str:
    """
    Generate unique block ID in format XXXX-XXXX-XXX.

    40 bits entropy (8 characters payload) + 3 characters checksum.
    """
    return ArmorID.generate()


def is_armor_id(block_id: str) -> bool:
    """Check if ID is armor format (XXXX-XXXX-XXX)."""
    clean = block_id.replace("-", "").upper()
    return len(clean) == 11 and all(c in ArmorID.ALPHABET for c in clean)


def uuid_to_armor_id(uuid_str: str) -> str:
    """Convert UUID to armor ID format."""
    return ArmorID.encode(uuid_str)


def migrate_block_id(block_id: str) -> tuple[str, bool]:
    """
    Migrate block ID to armor format if needed.

    Returns: (new_id, was_migrated)
    """
    if is_armor_id(block_id):
        return block_id, False
    # Legacy UUID -> armor
    return uuid_to_armor_id(block_id), True


def encode_block_id(block_id: str) -> str:
    """
    Encode block_id to armor format.
    If already armor ID - returns as is.
    """
    # Check: already armor ID?
    clean = block_id.replace("-", "").upper()
    if len(clean) == 11 and all(c in ArmorID.ALPHABET for c in clean):
        # Format to standard XXXX-XXXX-XXX
        return f"{clean[:4]}-{clean[4:8]}-{clean[8:]}"

    # Legacy: convert UUID
    return ArmorID.encode(block_id)


def decode_armor_code(armor_code: str) -> Optional[str]:
    """Decode armor code to hex prefix."""
    return ArmorID.decode(armor_code)


def match_armor_to_uuid(
    armor_code: str, expected_uuids: List[str], score_cutoff: float = 70.0
) -> Tuple[Optional[str], float]:
    """Match armor code to uuid. Uses fuzzy search for heavily damaged codes."""
    return ArmorID.match_to_uuid(armor_code, expected_uuids, score_cutoff)
