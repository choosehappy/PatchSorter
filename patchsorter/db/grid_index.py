"""Hierarchical grid index for converting spatial polygons to grid cells.

Copied and trimmed from ``prototyping/pre_agent_benchmarks/utils.py``.
Only the (i, j, level) triple representation is included here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

from shapely.geometry import Point, Polygon


@dataclass(frozen=True, order=True)
class GridCell:
    """Immutable, hashable (i, j, level) triple representing a grid cell.

    Attributes:
        i:     Column index (increases with x).
        j:     Row index (increases with y).
        level: Resolution level (0 = coarsest).
    """

    i: int
    j: int
    level: int

    def __repr__(self) -> str:
        return f"GridCell(i={self.i}, j={self.j}, level={self.level})"


class HierarchicalGridIndexIJPair:
    """Square grid hierarchical indexing system using (i, j, level) triples.

    Args:
        cell_size: Size of each square cell at level 0.  Typically the
            ``world_size`` setting value for the project.
    """

    def __init__(self, cell_size: float = 1.0) -> None:
        self.cell_size = cell_size

    def point_to_cell(self, x: float, y: float, level: int) -> GridCell:
        """Convert a point to a :class:`GridCell` at the specified level."""
        if level < 0:
            raise ValueError("Level must be non-negative")
        scaled_size = self.cell_size / (2 ** level)
        return GridCell(
            i=math.floor(x / scaled_size),
            j=math.floor(y / scaled_size),
            level=level,
        )

    def polygon_to_cells(self, polygon: Polygon, level: int) -> List[GridCell]:
        """Return all :class:`GridCell` objects at *level* whose centre lies
        inside *polygon*.

        Args:
            polygon: A Shapely ``Polygon`` defining the boundary.
            level:   Resolution level.

        Returns:
            Sorted list of :class:`GridCell` objects (sorted by ``(i, j)``).
        """
        if level < 0:
            raise ValueError("Level must be non-negative")

        scaled_size = self.cell_size / (2 ** level)
        min_x, min_y, max_x, max_y = polygon.bounds

        i_start = math.floor(min_x / scaled_size)
        i_end = math.floor(max_x / scaled_size)
        j_start = math.floor(min_y / scaled_size)
        j_end = math.floor(max_y / scaled_size)

        cells: List[GridCell] = []
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                cx = (i + 0.5) * scaled_size
                cy = (j + 0.5) * scaled_size
                if polygon.contains(Point(cx, cy)):
                    cells.append(GridCell(i=i, j=j, level=level))

        cells.sort()
        return cells
