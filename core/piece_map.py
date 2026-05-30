from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path


PIECE_STATUS_COMPLETE = "complete"
PIECE_STATUS_ACTIVE = "active"
PIECE_STATUS_PARTIAL = "partial"
PIECE_STATUS_EMPTY = "empty"
PIECE_STATUS_UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class PieceMapSnapshot:
    total_pieces: int
    display_cells: list[str]
    available: bool
    message: str = ""


class Aria2ControlFileParser:
    def parse(self, path: Path, *, max_display_cells: int = 8192) -> PieceMapSnapshot:
        try:
            raw = path.read_bytes()
        except OSError:
            return PieceMapSnapshot(
                total_pieces=0,
                display_cells=[],
                available=False,
                message="piece_map.no_data",
            )

        try:
            total_pieces, statuses = self._parse_raw(raw)
        except ValueError:
            return PieceMapSnapshot(
                total_pieces=0,
                display_cells=[],
                available=False,
                message="piece_map.parse_failed",
            )

        if total_pieces <= 0 or not statuses:
            return PieceMapSnapshot(
                total_pieces=0,
                display_cells=[],
                available=False,
                message="piece_map.no_data",
            )

        return PieceMapSnapshot(
            total_pieces=total_pieces,
            display_cells=self._build_display_cells(statuses, max_display_cells),
            available=True,
            message="",
        )

    def build_snapshot_from_rpc(
        self,
        *,
        bitfield_hex: str,
        num_pieces: int,
        active_count: int = 0,
        is_live: bool = False,
        max_display_cells: int = 8192,
    ) -> PieceMapSnapshot:
        if num_pieces <= 0:
            return PieceMapSnapshot(
                total_pieces=0,
                display_cells=[],
                available=False,
                message="piece_map.no_data",
            )

        statuses = self._statuses_from_hex_bitfield(bitfield_hex, num_pieces)
        if is_live and active_count > 0:
            self._overlay_active_frontier(statuses, active_count)
        return PieceMapSnapshot(
            total_pieces=num_pieces,
            display_cells=self._build_display_cells(statuses, max_display_cells),
            available=True,
            message="",
        )

    def _parse_raw(self, raw: bytes) -> tuple[int, list[str]]:
        if len(raw) < 34:
            raise ValueError("Control file is too short.")

        version_be = struct.unpack_from(">H", raw, 0)[0]
        if version_be == 1:
            endian = ">"
        elif version_be == 0:
            endian = "<"
        else:
            raise ValueError("Unsupported control file version.")

        offset = 0

        def read(fmt: str) -> int:
            nonlocal offset
            size = struct.calcsize(fmt)
            if offset + size > len(raw):
                raise ValueError("Unexpected end of control file.")
            value = struct.unpack_from(endian + fmt, raw, offset)[0]
            offset += size
            return int(value)

        _version = read("H")
        _extension = read("I")
        info_hash_length = read("I")
        if offset + info_hash_length > len(raw):
            raise ValueError("Invalid info hash length.")
        offset += info_hash_length

        piece_length = read("I")
        total_length = read("Q")
        _upload_length = read("Q")
        bitfield_length = read("I")
        if offset + bitfield_length > len(raw):
            raise ValueError("Invalid bitfield length.")
        bitfield = raw[offset : offset + bitfield_length]
        offset += bitfield_length

        inflight_count = read("I")
        inflight_indices: list[int] = []
        for _ in range(inflight_count):
            piece_index = read("I")
            _piece_size = read("I")
            piece_bitfield_length = read("I")
            if offset + piece_bitfield_length > len(raw):
                raise ValueError("Invalid in-flight piece bitfield length.")
            piece_bitfield = raw[offset : offset + piece_bitfield_length]
            offset += piece_bitfield_length
            if piece_index >= 0 and any(piece_bitfield):
                inflight_indices.append(piece_index)

        total_pieces = 0
        if piece_length > 0 and total_length > 0:
            total_pieces = math.ceil(total_length / piece_length)
        total_pieces = max(
            total_pieces,
            bitfield_length * 8,
            (max(inflight_indices) + 1) if inflight_indices else 0,
        )
        if total_pieces <= 0:
            return 0, []

        complete_flags = [False] * total_pieces
        for piece_index in range(total_pieces):
            byte_index = piece_index // 8
            if byte_index >= len(bitfield):
                break
            mask = 1 << (7 - (piece_index % 8))
            complete_flags[piece_index] = bool(bitfield[byte_index] & mask)

        active_set = set(inflight_indices)
        statuses: list[str] = []
        for piece_index in range(total_pieces):
            if piece_index in active_set:
                statuses.append(PIECE_STATUS_ACTIVE)
            elif complete_flags[piece_index]:
                statuses.append(PIECE_STATUS_COMPLETE)
            else:
                statuses.append(PIECE_STATUS_EMPTY)

        return total_pieces, statuses

    def _build_display_cells(
        self,
        statuses: list[str],
        max_display_cells: int,
    ) -> list[str]:
        if len(statuses) <= max_display_cells:
            return statuses

        group_size = math.ceil(len(statuses) / max_display_cells)
        cells: list[str] = []
        for start in range(0, len(statuses), group_size):
            group = statuses[start : start + group_size]
            cells.append(self._aggregate_status(group))
        return cells

    @staticmethod
    def _aggregate_status(group: list[str]) -> str:
        if not group:
            return PIECE_STATUS_UNAVAILABLE
        if PIECE_STATUS_ACTIVE in group:
            return PIECE_STATUS_ACTIVE
        if PIECE_STATUS_PARTIAL in group:
            return PIECE_STATUS_PARTIAL
        if all(status == PIECE_STATUS_COMPLETE for status in group):
            return PIECE_STATUS_COMPLETE
        if all(status == PIECE_STATUS_EMPTY for status in group):
            return PIECE_STATUS_EMPTY
        if any(status == PIECE_STATUS_COMPLETE for status in group):
            return PIECE_STATUS_PARTIAL
        return PIECE_STATUS_EMPTY

    @staticmethod
    def _statuses_from_hex_bitfield(bitfield_hex: str, num_pieces: int) -> list[str]:
        statuses = [PIECE_STATUS_EMPTY] * num_pieces
        if not bitfield_hex:
            return statuses

        try:
            bitfield = bytes.fromhex(bitfield_hex)
        except ValueError:
            return statuses

        for piece_index in range(num_pieces):
            byte_index = piece_index // 8
            if byte_index >= len(bitfield):
                break
            mask = 1 << (7 - (piece_index % 8))
            if bitfield[byte_index] & mask:
                statuses[piece_index] = PIECE_STATUS_COMPLETE
        return statuses

    @staticmethod
    def _overlay_active_frontier(statuses: list[str], active_count: int) -> None:
        if not statuses or active_count <= 0:
            return

        frontier_index = next(
            (index for index, status in enumerate(statuses) if status != PIECE_STATUS_COMPLETE),
            len(statuses) - 1,
        )
        pending = active_count
        for offset in range(len(statuses)):
            for candidate in (frontier_index + offset, frontier_index - offset):
                if pending <= 0:
                    return
                if 0 <= candidate < len(statuses) and statuses[candidate] == PIECE_STATUS_EMPTY:
                    statuses[candidate] = PIECE_STATUS_ACTIVE
                    pending -= 1
