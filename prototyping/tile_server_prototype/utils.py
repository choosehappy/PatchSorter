import math
from dataclasses import dataclass
from typing import List, Tuple
from shapely.geometry import Point, Polygon, MultiPolygon
from abc import ABC, abstractmethod

class HierarchicalGridIndex(ABC):
    """Abstract base class for hierarchical grid indexing systems."""
    
    @abstractmethod
    def point_to_cell(self, x: float, y: float, level: int) -> int:
        """Convert a point to a cell index at the specified level."""
        pass
    
    @abstractmethod
    def cell_to_point(self, cell: int) -> Tuple[float, float]:
        """Get the center point of a cell."""
        pass
    
    @abstractmethod
    def cell_to_boundary(self, cell: int) -> List[Tuple[float, float]]:
        """Get the boundary vertices of a cell."""
        pass
    
    @abstractmethod
    def cell_to_parent(self, cell: int, parent_level: int) -> int:
        """Get the parent cell at a coarser resolution."""
        pass
    
    @abstractmethod
    def cell_to_children(self, cell: int, child_level: int) -> List[int]:
        """Get all children cells at a finer resolution."""
        pass
    
    @abstractmethod
    def get_resolution(self, cell: int) -> int:
        """Get the resolution level of a cell."""
        pass
    
    @abstractmethod
    def is_valid_cell(self, cell: int) -> bool:
        """Check if a cell index is valid."""
        pass

    @abstractmethod
    def polygon_to_cells(self, polygon: Polygon, level: int) -> List[int]:
        """
        Return all cells at *level* whose centre lies inside *polygon*.
        Equivalent to H3's polygonToCells function.

        Args:
            polygon: A Shapely Polygon defining the boundary.
            level:   Resolution level.

        Returns:
            List of cell indices whose centres are inside the polygon.
        """
        pass


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


class HierarchicalGridIndexIJPair(HierarchicalGridIndex):
    """
    Square grid hierarchical indexing system for Euclidean space that
    represents cells as :class:`GridCell` ``(i, j, level)`` triples
    rather than packing them into a single 64-bit integer.

    This makes the spatial coordinates directly inspectable without
    any bit-manipulation, at the cost of not producing sortable integer
    cell IDs.  The API mirrors :class:`HierarchicalGridIndexIJ` exactly,
    but every method that accepts or returns a *cell* uses
    :class:`GridCell` instead of ``int``.
    """

    def __init__(self, cell_size: float = 1.0) -> None:
        """
        Args:
            cell_size: Size of each square cell at level 0.
        """
        self.cell_size = cell_size

    # ------------------------------------------------------------------
    # HierarchicalGridIndex interface
    # ------------------------------------------------------------------

    def point_to_cell(self, x: float, y: float, level: int) -> GridCell:
        """
        Convert a point to a :class:`GridCell` at the specified level.

        Args:
            x:     X coordinate.
            y:     Y coordinate.
            level: Resolution level (0 = coarsest).

        Returns:
            :class:`GridCell` containing the point.
        """
        if level < 0:
            raise ValueError("Level must be non-negative")
        scaled_size = self.cell_size / (2 ** level)
        return GridCell(i=math.floor(x / scaled_size),
                        j=math.floor(y / scaled_size),
                        level=level)

    def cell_to_point(self, cell: GridCell) -> Tuple[float, float]:
        """
        Get the centre point of a :class:`GridCell`.

        Returns:
            ``(x, y)`` coordinates of the cell centre.
        """
        scaled_size = self.cell_size / (2 ** cell.level)
        return ((cell.i + 0.5) * scaled_size,
                (cell.j + 0.5) * scaled_size)

    def cell_to_boundary(self, cell: GridCell) -> List[Tuple[float, float]]:
        """
        Get the boundary vertices of a :class:`GridCell`.

        Returns:
            Five ``(x, y)`` tuples forming a closed counter-clockwise square.
        """
        s = self.cell_size / (2 ** cell.level)
        x0, y0 = cell.i * s, cell.j * s
        return [
            (x0,     y0),      # bottom-left
            (x0 + s, y0),      # bottom-right
            (x0 + s, y0 + s),  # top-right
            (x0,     y0 + s),  # top-left
            (x0,     y0),      # close polygon
        ]

    def cell_to_parent(self, cell: GridCell, parent_level: int) -> GridCell:
        """
        Return the parent :class:`GridCell` at a coarser resolution.

        Args:
            cell:         Child cell.
            parent_level: Target level (must be < ``cell.level``).
        """
        if parent_level >= cell.level or parent_level < 0:
            raise ValueError("Parent level must be less than child level")
        delta = cell.level - parent_level
        return GridCell(i=cell.i >> delta,
                        j=cell.j >> delta,
                        level=parent_level)

    def cell_to_children(self, cell: GridCell, child_level: int) -> List[GridCell]:
        """
        Return all :class:`GridCell` children at a finer resolution.

        Children are returned in row-major (i-major) order.

        Args:
            cell:        Parent cell.
            child_level: Target level (must be > ``cell.level``).
        """
        if child_level <= cell.level:
            raise ValueError("Child level must be greater than parent level")
        delta = child_level - cell.level
        factor = 2 ** delta
        i_base = cell.i * factor
        j_base = cell.j * factor
        return [
            GridCell(i=i_base + di, j=j_base + dj, level=child_level)
            for di in range(factor)
            for dj in range(factor)
        ]

    def get_resolution(self, cell: GridCell) -> int:
        """Return the resolution level of *cell*."""
        return cell.level

    def is_valid_cell(self, cell: GridCell) -> bool:
        """Return ``True`` if *cell* has a non-negative level ≤ 15."""
        return isinstance(cell, GridCell) and 0 <= cell.level <= 15

    # TODO: Make this more efficient by drawing the polygon onto a raster grid and checking which cells it covers.
    def polygon_to_cells(self, polygon: Polygon, level: int) -> List[GridCell]:
        """
        Return all :class:`GridCell` objects at *level* whose centre lies
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
        i_end   = math.floor(max_x / scaled_size)
        j_start = math.floor(min_y / scaled_size)
        j_end   = math.floor(max_y / scaled_size)

        cells: List[GridCell] = []
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                cx = (i + 0.5) * scaled_size
                cy = (j + 0.5) * scaled_size
                if polygon.contains(Point(cx, cy)):
                    cells.append(GridCell(i=i, j=j, level=level))

        cells.sort()
        return cells

    def cells_to_polygon(self, cells: List[GridCell]) -> MultiPolygon:
        """
        Convert a collection of :class:`GridCell` objects into a
        :class:`~shapely.geometry.MultiPolygon`.

        Useful for visualising the covered area or computing union geometry.

        Args:
            cells: Iterable of :class:`GridCell` objects at any level.

        Returns:
            ``MultiPolygon`` (or ``Polygon``) representing the union of all
            cell footprints.
        """
        from shapely.ops import unary_union
        polys = [Polygon(self.cell_to_boundary(c)[:-1]) for c in cells]
        return unary_union(polys)

    def grid_distance(self, a: GridCell, b: GridCell) -> int:
        """
        Return the Chebyshev (chessboard) distance between two cells.

        Both cells must be at the same level; they are coarsened to the
        lower level first if they differ.

        Args:
            a: First cell.
            b: Second cell.

        Returns:
            Chebyshev distance in cell units at the common level.

        Raises:
            ValueError: If cells are at different levels and coarsening is
                        ambiguous (b.level < a.level, handled symmetrically).
        """
        if a.level != b.level:
            common = min(a.level, b.level)
            a = self.cell_to_parent(a, common) if a.level > common else a
            b = self.cell_to_parent(b, common) if b.level > common else b
        return max(abs(a.i - b.i), abs(a.j - b.j))

    def k_ring(self, cell: GridCell, k: int) -> List[GridCell]:
        """
        Return all cells within Chebyshev distance *k* of *cell*
        (inclusive of *cell* itself).

        This is the square analogue of H3's ``gridDisk`` function.

        Args:
            cell: Centre cell.
            k:    Ring radius (0 returns just *cell*).

        Returns:
            List of :class:`GridCell` objects, sorted by ``(i, j)``.
        """
        if k < 0:
            raise ValueError("k must be non-negative")
        result = [
            GridCell(i=cell.i + di, j=cell.j + dj, level=cell.level)
            for di in range(-k, k + 1)
            for dj in range(-k, k + 1)
        ]
        result.sort()
        return result