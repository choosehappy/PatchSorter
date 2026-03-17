import psycopg2
import math  
from typing import Optional, Tuple, List, Union  
from abc import ABC, abstractmethod
from shapely.geometry import Polygon, Point, MultiPolygon, box
from dataclasses import dataclass

DB_PARAMS = {
    'host': 'localhost',
    'database': 'testdb',
    'user': 'testuser',
    'password': 'mypassword',
    'port': 5432
}

def insert_n_rows(n=1_000_000):
    """
    Insert n rows into sample_data table using PostgreSQL's generate_series
    
    Args:
        n: Number of rows to insert (default 1 million)
    """
    conn = psycopg2.connect(**DB_PARAMS)
    cur = conn.cursor()
    
    print(f"Creating table and inserting {n:,} rows...")
    
    # Create table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sample_data (
            id BIGSERIAL PRIMARY KEY,
            value DOUBLE PRECISION,
            category VARCHAR(50),
            timestamp TIMESTAMP
        );
    """)
    
    # Insert data using generate_series
    cur.execute(f"""
        INSERT INTO sample_data (value, category, timestamp)
        SELECT 
            50 + (random() - 0.5) * 30 + (random() - 0.5) * 30,
            CHR(65 + floor(random() * 5)::int),
            NOW() - (random() * INTERVAL '365 days')
        FROM generate_series(1, {n});
    """)
    
    # Create index
    cur.execute("CREATE INDEX IF NOT EXISTS idx_value ON sample_data(value);")
    
    # Analyze table
    cur.execute("ANALYZE sample_data;")
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"✓ Successfully inserted {n:,} rows")


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

class HierarchicalGridIndexZOrder(HierarchicalGridIndex):
    """
    Square grid hierarchical indexing system for Euclidean space,
    using Z-order curve (Morton code) for encoding.

    Cell index layout (64 bits):
        - bits 63-58: resolution level (6 bits, 0-15)
        - bits 57-0 : Morton code – bits of i and j interleaved,
                      i at even positions, j at odd positions (29 bits each)

    Spatial locality: cells that are close in (i, j) space map to
    nearby Morton codes, which improves range-query performance when
    cell indices are stored in a B-tree index.
    """

    def __init__(self, cell_size: float = 1.0):
        """
        Initialize the grid index.

        Args:
            cell_size: Size of each square cell at level 0
        """
        self.cell_size = cell_size

    # ------------------------------------------------------------------
    # Morton-code helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _encode_morton(i: int, j: int) -> int:
        """Interleave bits of i and j to produce a 58-bit Morton code.

        Bit layout of the result:
            bit 0  → i bit 0
            bit 1  → j bit 0
            bit 2  → i bit 1
            bit 3  → j bit 1
            ...
            bit 56 → i bit 28
            bit 57 → j bit 28
        """
        i = i & 0x1FFFFFFF  # keep 29 bits
        j = j & 0x1FFFFFFF
        code = 0
        for bit in range(29):
            code |= ((i >> bit) & 1) << (2 * bit)
            code |= ((j >> bit) & 1) << (2 * bit + 1)
        return code

    @staticmethod
    def _decode_morton(code: int) -> Tuple[int, int]:
        """Deinterleave a 58-bit Morton code back to (i, j) coordinates."""
        i = 0
        j = 0
        for bit in range(29):
            i |= ((code >> (2 * bit)) & 1) << bit
            j |= ((code >> (2 * bit + 1)) & 1) << bit
        return i, j

    # ------------------------------------------------------------------
    # HierarchicalGridIndex interface
    # ------------------------------------------------------------------

    def point_to_cell(self, x: float, y: float, level: int) -> int:
        """
        Convert a point to a cell index at the specified level.
        Equivalent to H3's latLngToCell function.

        Args:
            x: X coordinate
            y: Y coordinate
            level: Resolution level (0 = coarsest)

        Returns:
            Cell index as encoded integer (level bits | Morton code)
        """
        if level < 0:
            raise ValueError("Level must be non-negative")

        scale = 2 ** level
        scaled_size = self.cell_size / scale

        i = math.floor(x / scaled_size)
        j = math.floor(y / scaled_size)

        morton = self._encode_morton(i, j)
        return (level << 58) | morton

    def cell_to_point(self, cell: int) -> Tuple[float, float]:
        """
        Get the center point of a cell.
        Equivalent to H3's cellToLatLng function.

        Args:
            cell: Cell index

        Returns:
            (x, y) coordinates of cell center
        """
        level = self._get_level(cell)
        scale = 2 ** level
        scaled_size = self.cell_size / scale

        i, j = self._decode_morton(cell & 0x3FFFFFFFFFFFFFF)

        x = (i + 0.5) * scaled_size
        y = (j + 0.5) * scaled_size
        return (x, y)

    def cell_to_boundary(self, cell: int) -> List[Tuple[float, float]]:
        """
        Get the boundary vertices of a cell.
        Equivalent to H3's cellToBoundary function.

        Args:
            cell: Cell index

        Returns:
            List of (x, y) tuples representing the square boundary
            (counter-clockwise, polygon closed)
        """
        level = self._get_level(cell)
        scale = 2 ** level
        scaled_size = self.cell_size / scale

        i, j = self._decode_morton(cell & 0x3FFFFFFFFFFFFFF)

        return [
            (i * scaled_size,           j * scaled_size),           # bottom-left
            ((i + 1) * scaled_size,     j * scaled_size),           # bottom-right
            ((i + 1) * scaled_size,     (j + 1) * scaled_size),     # top-right
            (i * scaled_size,           (j + 1) * scaled_size),     # top-left
            (i * scaled_size,           j * scaled_size),           # close polygon
        ]

    def cell_to_parent(self, cell: int, parent_level: int) -> int:
        """
        Get the parent cell at a coarser resolution.
        Equivalent to H3's cellToParent function.

        Args:
            cell: Child cell index
            parent_level: Target parent level (must be < child's level)

        Returns:
            Parent cell index
        """
        child_level = self._get_level(cell)
        if parent_level >= child_level or parent_level < 0:
            raise ValueError("Parent level must be less than child level")

        x, y = self.cell_to_point(cell)
        return self.point_to_cell(x, y, parent_level)

    def cell_to_children(self, cell: int, child_level: int) -> List[int]:
        """
        Get all children cells at a finer resolution.
        Equivalent to H3's cellToChildren function.

        Children are returned sorted by Morton code so that spatially
        adjacent children appear consecutively in the list.

        Args:
            cell: Parent cell index
            child_level: Target child level (must be > parent's level)

        Returns:
            List of child cell indices in Z-order (Morton) order
        """
        parent_level = self._get_level(cell)
        if child_level <= parent_level:
            raise ValueError("Child level must be greater than parent level")

        boundary = self.cell_to_boundary(cell)
        min_x = min(p[0] for p in boundary[:-1])
        min_y = min(p[1] for p in boundary[:-1])
        max_x = max(p[0] for p in boundary[:-1])
        max_y = max(p[1] for p in boundary[:-1])

        scale = 2 ** child_level
        scaled_size = self.cell_size / scale

        i_start = math.floor(min_x / scaled_size)
        # Subtract epsilon so the exclusive upper boundary doesn't bleed
        # into the next cell (mirrors the IJ implementation).
        i_end = math.floor((max_x - 1e-10) / scaled_size)
        j_start = math.floor(min_y / scaled_size)
        j_end = math.floor((max_y - 1e-10) / scaled_size)

        children = []
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                morton = self._encode_morton(i, j)
                children.append((child_level << 58) | morton)

        # Sort by Morton code to expose spatial locality.
        children.sort()
        return children

    def get_resolution(self, cell: int) -> int:
        """
        Get the resolution level of a cell.
        Equivalent to H3's getResolution function.

        Args:
            cell: Cell index

        Returns:
            Resolution level
        """
        return self._get_level(cell)

    def is_valid_cell(self, cell: int) -> bool:
        """
        Check if a cell index is valid.
        Equivalent to H3's isValidCell function.

        Args:
            cell: Cell index to validate

        Returns:
            True if valid, False otherwise
        """
        if cell == 0:
            return False
        level = self._get_level(cell)
        return 0 <= level <= 15  # support up to level 15, like H3

    def polygon_to_cells(self, polygon: Polygon, level: int) -> List[int]:
        """
        Return all cells at *level* whose centre lies inside *polygon*.
        Equivalent to H3's polygonToCells function.

        Uses recursive Morton-range decomposition: the bounding box is
        subdivided into Z-order quadrants and entire quadrants that do not
        intersect the polygon are pruned, giving sub-linear behaviour for
        geographically compact polygons at high resolutions.

        Args:
            polygon: A Shapely Polygon defining the boundary.
            level:   Resolution level.

        Returns:
            List of cell indices whose centres are inside the polygon,
            sorted in Z-order (Morton) order.
        """
        if level < 0:
            raise ValueError("Level must be non-negative")

        cells: List[int] = []

        def recurse(i_lo: int, j_lo: int, quad_level: int) -> None:
            """
            Test the quad-tree node at (i_lo, j_lo) at quad_level.
            If it intersects the polygon, either collect all its leaf
            cells (if fully contained) or recurse deeper.
            """
            scale = 2 ** quad_level
            scaled_size = self.cell_size / scale
            side = scaled_size  # one cell wide at quad_level

            # Number of target-level cells along one side of this quad
            cells_per_side = 2 ** (level - quad_level)

            # Bounding box of this quad in world coordinates
            x0 = i_lo * scaled_size
            y0 = j_lo * scaled_size
            x1 = x0 + cells_per_side * (self.cell_size / 2 ** level)
            y1 = y0 + cells_per_side * (self.cell_size / 2 ** level)
            quad_box = box(x0, y0, x1, y1)

            if not polygon.intersects(quad_box):
                return  # prune: no overlap at all

            if quad_level == level:
                # Leaf: test cell centre
                cx = (i_lo + 0.5) * scaled_size
                cy = (j_lo + 0.5) * scaled_size
                if polygon.contains(Point(cx, cy)):
                    morton = self._encode_morton(i_lo, j_lo)
                    cells.append((level << 58) | morton)
                return

            if polygon.contains(quad_box):
                # Entire quad is inside — collect all leaf cells without
                # further point-in-polygon tests.
                next_scale = 2 ** level
                next_size = self.cell_size / next_scale
                factor = 2 ** (level - quad_level)
                i_base = i_lo * factor
                j_base = j_lo * factor
                for di in range(factor):
                    for dj in range(factor):
                        morton = self._encode_morton(i_base + di, j_base + dj)
                        cells.append((level << 58) | morton)
                return

            # Partial overlap — recurse into four children
            mid_level = quad_level + 1
            factor = 2 ** (level - mid_level)
            i_mid = i_lo * 2
            j_mid = j_lo * 2
            recurse(i_mid,     j_mid,     mid_level)
            recurse(i_mid + 1, j_mid,     mid_level)
            recurse(i_mid,     j_mid + 1, mid_level)
            recurse(i_mid + 1, j_mid + 1, mid_level)

        # Seed the recursion from level-0 cells that overlap the polygon bbox
        min_x, min_y, max_x, max_y = polygon.bounds
        i_start = math.floor(min_x / self.cell_size)
        i_end   = math.floor(max_x / self.cell_size)
        j_start = math.floor(min_y / self.cell_size)
        j_end   = math.floor(max_y / self.cell_size)

        for i0 in range(i_start, i_end + 1):
            for j0 in range(j_start, j_end + 1):
                recurse(i0, j0, 0)

        cells.sort()
        return cells

    def polygon_to_morton_ranges(self, polygon: Polygon, level: int, max_recursion_depth: Optional[int] = None) -> List[Tuple[int, int]]:
        """
        Return a minimal list of Morton-code ranges that cover all cells at
        *level* whose centre lies inside *polygon*.

        Each ``(lo, hi)`` pair is suitable for a SQL
        ``column BETWEEN lo AND hi`` predicate on the 64-bit cell-ID column.

        **Why contiguous ranges work for Z-order**

        Because every aligned $2^k \\times 2^k$ block of cells maps to a
        *contiguous* run of Morton codes::

            encode_morton(i_base + di, j_base + dj)
                = encode_morton(i_base, j_base) + encode_morton(di, dj)

        when ``i_base`` and ``j_base`` are multiples of ``2^k`` and
        ``0 ≤ di, dj < 2^k``.  Since ``encode_morton`` is a bijection on
        ``[0, 2^k) × [0, 2^k) → [0, 4^k)``, the complete block spans the
        range ``[morton_base, morton_base + 4^k - 1]`` with no gaps.

        The same quad-tree recursion as :meth:`polygon_to_cells` is used:

        * **No intersection** – prune the subtree entirely.
        * **Fully contained** – emit a single ``(lo, hi)`` range for the
          entire aligned block (``span = 4^k - 1 = factor² - 1``).
        * **Partial overlap** – recurse into the four Z-order children.
        * **Leaf** – point-in-polygon test; emit ``(cell, cell)`` if inside.

        Adjacent or overlapping raw ranges are merged before returning, so
        the output list is the minimum number of disjoint ``BETWEEN`` spans.

        Args:
            polygon:             A Shapely ``Polygon`` defining the query boundary.
            level:               Resolution level (must be ≥ 0).
            max_recursion_depth: Optional cap on quad-tree recursion depth
                                 (measured from level 0).  When the recursion
                                 reaches this depth before hitting the target
                                 *level*, the entire remaining sub-quad is
                                 emitted as a single Morton range, trading
                                 precision (some non-contained cells may be
                                 included) for speed.  ``None`` (default)
                                 means unlimited recursion down to *level*.

        Returns:
            Sorted, merged list of ``(range_min, range_max)`` inclusive
            64-bit cell-ID ranges.  Empty list if the polygon covers no cells.

        Example::

            ranges = idx.polygon_to_morton_ranges(qbox, level=10)
            placeholders = " OR ".join(
                f"grid_id_z BETWEEN {lo} AND {hi}" for lo, hi in ranges
            )
        """
        if level < 0:
            raise ValueError("Level must be non-negative")
        if max_recursion_depth is not None and max_recursion_depth < 0:
            raise ValueError("max_recursion_depth must be non-negative")

        raw_ranges: List[Tuple[int, int]] = []
        level_prefix = level << 58
        leaf_size = self.cell_size / (2 ** level)

        def recurse(i_lo: int, j_lo: int, quad_level: int, depth: int) -> None:
            factor = 2 ** (level - quad_level)
            scaled_size = self.cell_size / (2 ** quad_level)

            x0 = i_lo * scaled_size
            y0 = j_lo * scaled_size
            x1 = x0 + factor * leaf_size
            y1 = y0 + factor * leaf_size
            quad_box = box(x0, y0, x1, y1)

            if not polygon.intersects(quad_box):
                return  # prune: no overlap

            i_base = i_lo * factor
            j_base = j_lo * factor
            morton_base = self._encode_morton(i_base, j_base)

            if quad_level == level:
                # Leaf cell: test whether its centre is inside the polygon.
                cx = (i_base + 0.5) * leaf_size
                cy = (j_base + 0.5) * leaf_size
                if polygon.contains(Point(cx, cy)):
                    cell_id = level_prefix | morton_base
                    raw_ranges.append((cell_id, cell_id))
                return

            if polygon.contains(quad_box) or (
                max_recursion_depth is not None and depth >= max_recursion_depth
            ):
                # Either entirely inside, or depth cap reached — emit one range.
                span = factor * factor - 1
                raw_ranges.append(
                    (level_prefix | morton_base,
                     level_prefix | (morton_base + span))
                )
                return

            # Partial overlap: recurse into four Z-order children.
            mid = quad_level + 1
            i2, j2 = i_lo * 2, j_lo * 2
            recurse(i2,     j2,     mid, depth + 1)
            recurse(i2 + 1, j2,     mid, depth + 1)
            recurse(i2,     j2 + 1, mid, depth + 1)
            recurse(i2 + 1, j2 + 1, mid, depth + 1)

        # Seed from every level-0 cell that overlaps the polygon bounding box.
        min_x, min_y, max_x, max_y = polygon.bounds
        i_start = math.floor(min_x / self.cell_size)
        i_end   = math.floor(max_x / self.cell_size)
        j_start = math.floor(min_y / self.cell_size)
        j_end   = math.floor(max_y / self.cell_size)

        for i0 in range(i_start, i_end + 1):
            for j0 in range(j_start, j_end + 1):
                recurse(i0, j0, 0, 0)

        # Merge adjacent / overlapping ranges to minimise BETWEEN clauses.
        if not raw_ranges:
            return []

        raw_ranges.sort()
        merged: List[Tuple[int, int]] = [raw_ranges[0]]
        for lo, hi in raw_ranges[1:]:
            prev_lo, prev_hi = merged[-1]
            if lo <= prev_hi + 1:          # adjacent or overlapping
                merged[-1] = (prev_lo, max(prev_hi, hi))
            else:
                merged.append((lo, hi))

        return merged

    def _get_level(self, cell: int) -> int:
        """Extract level from encoded cell index."""
        return cell >> 58


class HierarchicalGridIndexIJ(HierarchicalGridIndex):  
    """  
    Square grid hierarchical indexing system for Euclidean space,  
    replicating H3's API using floor operations instead of hexagonal grids.  
    """  
      
    def __init__(self, cell_size: float = 1.0):  
        """  
        Initialize the grid index.  
          
        Args:  
            cell_size: Size of each square cell at level 0  
        """  
        self.cell_size = cell_size  
      
    def point_to_cell(self, x: float, y: float, level: int) -> int:  
        """  
        Convert a point to a cell index at the specified level.  
        Equivalent to H3's latLngToCell function.  
          
        Args:  
            x: X coordinate  
            y: Y coordinate      
            level: Resolution level (0 = coarsest)  
              
        Returns:  
            Cell index as encoded integer  
        """  
        if level < 0:  
            raise ValueError("Level must be non-negative")  
              
        # Scale factor based on level (each level increases resolution by 2x)  
        scale = 2 ** level  
        scaled_size = self.cell_size / scale  
          
        # Adjust for negative coordinates to ensure correct cell calculation  
        i = math.floor(x / scaled_size)  
        j = math.floor(y / scaled_size)  
          
        # Encode into single integer: level (6 bits) + i (29 bits) + j (29 bits) = 64 bits
        return (level << 58) | ((i & 0x1FFFFFFF) << 29) | (j & 0x1FFFFFFF)  
      
    def cell_to_point(self, cell: int) -> Tuple[float, float]:  
        """  
        Get the center point of a cell.  
        Equivalent to H3's cellToLatLng function.  
          
        Args:  
            cell: Cell index  
              
        Returns:  
            (x, y) coordinates of cell center  
        """  
        level = self._get_level(cell)  
        scale = 2 ** level  
        scaled_size = self.cell_size / scale  
          
        i = self._get_i(cell)  
        j = self._get_j(cell)  
          
        # Center of the cell  
        x = (i + 0.5) * scaled_size  
        y = (j + 0.5) * scaled_size  
          
        return (x, y)  
      
    def cell_to_boundary(self, cell: int) -> List[Tuple[float, float]]:
        """  
        Get the boundary vertices of a cell.  
        Equivalent to H3's cellToBoundary function.  
          
        Args:  
            cell: Cell index  
              
        Returns:  
            List of (x, y) tuples representing the square boundary  
        """  
        level = self._get_level(cell)  
        scale = 2 ** level  
        scaled_size = self.cell_size / scale  
          
        i = self._get_i(cell)  
        j = self._get_j(cell)  
          
        # Square boundary vertices (counter-clockwise)  
        return [  
            (i * scaled_size, j * scaled_size),           # bottom-left  
            ((i + 1) * scaled_size, j * scaled_size),     # bottom-right  
            ((i + 1) * scaled_size, (j + 1) * scaled_size), # top-right  
            (i * scaled_size, (j + 1) * scaled_size),     # top-left  
            (i * scaled_size, j * scaled_size)            # close polygon  
        ]  
      
    def cell_to_parent(self, cell: int, parent_level: int) -> int:  
        """  
        Get the parent cell at a coarser resolution.  
        Equivalent to H3's cellToParent function.  
          
        Args:  
            cell: Child cell index  
            parent_level: Target parent level (must be < child's level)  
              
        Returns:  
            Parent cell index  
        """  
        child_level = self._get_level(cell)  
        if parent_level >= child_level or parent_level < 0:  
            raise ValueError("Parent level must be less than child level")  
          
        # Get the point at child level and convert to parent level  
        x, y = self.cell_to_point(cell)  
        return self.point_to_cell(x, y, parent_level)  
      
    def cell_to_children(self, cell: int, child_level: int) -> List[int]:  
        """  
        Get all children cells at a finer resolution.  
        Equivalent to H3's cellToChildren function.  
          
        Args:  
            cell: Parent cell index  
            child_level: Target child level (must be > parent's level)  
              
        Returns:  
            List of child cell indices  
        """  
        parent_level = self._get_level(cell)  
        if child_level <= parent_level:  
            raise ValueError("Child level must be greater than parent level")  
          
        # Get boundary and generate children grid  
        boundary = self.cell_to_boundary(cell)  
        min_x = min(p[0] for p in boundary[:-1])  
        min_y = min(p[1] for p in boundary[:-1])  
        max_x = max(p[0] for p in boundary[:-1])  
        max_y = max(p[1] for p in boundary[:-1])  
          
        children = []  
        scale = 2 ** child_level  
        scaled_size = self.cell_size / scale  
          
        i_start = math.floor(min_x / scaled_size)  
        # Use a small epsilon to handle boundary edge case - the max coordinate
        # is exclusive (belongs to the next cell), so we subtract a tiny amount
        i_end = math.floor((max_x - 1e-10) / scaled_size)  
        j_start = math.floor(min_y / scaled_size)  
        j_end = math.floor((max_y - 1e-10) / scaled_size)  
          
        for i in range(i_start, i_end + 1):  
            for j in range(j_start, j_end + 1):  
                child = (child_level << 58) | ((i & 0x1FFFFFFF) << 29) | (j & 0x1FFFFFFF)  
                children.append(child)  
          
        return children  
      
    def get_resolution(self, cell: int) -> int:  
        """  
        Get the resolution level of a cell.  
        Equivalent to H3's getResolution function.  
          
        Args:  
            cell: Cell index  
              
        Returns:  
            Resolution level  
        """  
        return self._get_level(cell)  
      
    def is_valid_cell(self, cell: int) -> bool:  
        """  
        Check if a cell index is valid.  
        Equivalent to H3's isValidCell function.  
          
        Args:  
            cell: Cell index to validate  
              
        Returns:  
            True if valid, False otherwise  
        """  
        if cell == 0:  
            return False  
          
        level = self._get_level(cell)  
        return 0 <= level <= 15  # Support up to level 15 like H3  
      
    def _get_level(self, cell: int) -> int:  
        """Extract level from encoded cell index."""  
        return cell >> 58  
      
    def _get_i(self, cell: int) -> int:  
        """Extract i coordinate from encoded cell index."""  
        return (cell >> 29) & 0x1FFFFFFF  
      
    def _get_j(self, cell: int) -> int:  
        """Extract j coordinate from encoded cell index."""  
        return cell & 0x1FFFFFFF  

    def polygon_to_cells(self, polygon: Polygon, level: int) -> List[int]:
        """
        Return all cells at *level* whose centre lies inside *polygon*.
        Equivalent to H3's polygonToCells function.

        Args:
            polygon: A Shapely Polygon defining the boundary.
            level:   Resolution level.

        Returns:
            List of cell indices.
        """
        if level < 0:
            raise ValueError("Level must be non-negative")

        min_x, min_y, max_x, max_y = polygon.bounds

        scale = 2 ** level
        scaled_size = self.cell_size / scale

        i_start = math.floor(min_x / scaled_size)
        i_end   = math.floor(max_x / scaled_size)
        j_start = math.floor(min_y / scaled_size)
        j_end   = math.floor(max_y / scaled_size)

        cells = []
        for i in range(i_start, i_end + 1):
            for j in range(j_start, j_end + 1):
                cx = (i + 0.5) * scaled_size
                cy = (j + 0.5) * scaled_size
                if polygon.contains(Point(cx, cy)):
                    cells.append((level << 58) | ((i & 0x1FFFFFFF) << 29) | (j & 0x1FFFFFFF))

        return cells


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


# ---------------------------------------------------------------------------
# SQL function registries
# ---------------------------------------------------------------------------

class HierarchicalGridSQLRegistry(ABC):
    """Abstract base class for registering HierarchicalGridIndex SQL helper
    functions into a PostgreSQL database.

    Each concrete subclass corresponds to one cell-encoding variant
    (Morton/Z-order or IJ) and provides the correct DDL for the
    ``cell_to_parent`` SQL function used by pg_ivm / materialized-view
    aggregation pipelines.

    Usage::

        registry = HierarchicalGridSQLRegistryZOrder()
        registry.register(conn)          # CREATE OR REPLACE FUNCTION …
        registry.is_registered(conn)     # True
        registry.drop(conn)              # DROP FUNCTION …
    """

    #: Default PostgreSQL function name used when none is supplied to __init__.
    DEFAULT_FUNCTION_NAME: str = "cell_to_parent"

    def __init__(self, function_name: Optional[str] = None) -> None:
        """
        Args:
            function_name: Override the PostgreSQL function name.  Useful when
                both encodings must coexist in the same schema (e.g.
                ``cell_to_parent_zorder`` and ``cell_to_parent_ij``).
                Defaults to ``"cell_to_parent"``.
        """
        self.function_name: str = function_name or self.DEFAULT_FUNCTION_NAME

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def get_cell_to_parent_sql(self) -> str:
        """Return the ``CREATE OR REPLACE FUNCTION`` DDL string for
        ``cell_to_parent(cell BIGINT, parent_level INT) RETURNS BIGINT``.

        The returned string must be executable as a single statement via
        ``cursor.execute()``.
        """
        pass

    # ------------------------------------------------------------------
    # Concrete helpers
    # ------------------------------------------------------------------

    def register(self, conn) -> None:
        """Create (or replace) the SQL function in the connected database.

        Safe to call multiple times — uses ``CREATE OR REPLACE FUNCTION``.
        Commits the transaction when ``conn.autocommit`` is ``False``.

        Args:
            conn: An open ``psycopg2`` connection.
        """
        with conn.cursor() as cur:
            cur.execute(self.get_cell_to_parent_sql())
        if not conn.autocommit:
            conn.commit()

    def drop(self, conn, if_exists: bool = True) -> None:
        """Drop the SQL function from the database.

        Args:
            conn:       An open ``psycopg2`` connection.
            if_exists:  When ``True`` (default), suppress the error if the
                        function does not exist (``DROP FUNCTION IF EXISTS``).
        """
        qualifier = "IF EXISTS" if if_exists else ""
        with conn.cursor() as cur:
            cur.execute(
                f"DROP FUNCTION {qualifier} {self.function_name}(BIGINT, INT) CASCADE;"
            )
        if not conn.autocommit:
            conn.commit()

    def is_registered(self, conn) -> bool:
        """Return ``True`` if the function currently exists in the database.

        Checks ``pg_proc`` for a function with the expected name and the
        exact argument signature ``(cell bigint, parent_level integer)``.

        Args:
            conn: An open ``psycopg2`` connection.
        """
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM   pg_proc p
                JOIN   pg_namespace n ON n.oid = p.pronamespace
                WHERE  p.proname = %s
                  AND  pg_catalog.pg_get_function_arguments(p.oid)
                         = 'cell bigint, parent_level integer'
                """,
                (self.function_name,),
            )
            return cur.fetchone() is not None


class HierarchicalGridSQLRegistryZOrder(HierarchicalGridSQLRegistry):
    """SQL function registry for the Morton/Z-order cell encoding.

    Registers a ``cell_to_parent(BIGINT, INT) RETURNS BIGINT`` function
    that coarsens a Morton-encoded 64-bit cell identifier.

    Bit layout of a cell ID:

    +-----------+---------+------------------------------------------+
    | Bits      | Field   | Notes                                    |
    +===========+=========+==========================================+
    | 63 – 58   | level   | 6 bits                                   |
    +-----------+---------+------------------------------------------+
    | 57 –  0   | Morton  | 58-bit interleaved i/j                   |
    |           | code    | (i at even positions, j at odd)          |
    +-----------+---------+------------------------------------------+

    Coarsening shifts the 58-bit Morton code right by
    ``2 * (child_level - parent_level)`` bits, which simultaneously
    floors both ``i`` and ``j`` by the level difference — equivalent to
    ``floor(i / 2^Δ)`` and ``floor(j / 2^Δ)`` — in a single operation.

    Matches the Python implementation in :class:`HierarchicalGridIndexZOrder`.
    """

    def get_cell_to_parent_sql(self) -> str:
        return f"""\
CREATE OR REPLACE FUNCTION {self.function_name}(cell BIGINT, parent_level INT)
RETURNS BIGINT LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = public AS $$
    -- Morton (Z-order) encoding: bits 63-58 = level, bits 57-0 = interleaved i/j.
    -- i occupies even bit positions (0, 2, 4, …), j occupies odd positions (1, 3, 5, …).
    -- Coarsen by right-shifting the Morton code by 2*(child_level - parent_level):
    --   this simultaneously floors both i and j by the level difference in one step,
    --   equivalent to floor(i / 2^Δ) and floor(j / 2^Δ) for each coordinate.
    -- 288230376151711743 = 0x3FFFFFFFFFFFFFF = 2^58 - 1  (strip the 6-bit level tag)
    SELECT (parent_level::BIGINT << 58)
         | ((cell & 288230376151711743::BIGINT) >> (2 * ((cell >> 58)::INT - parent_level)))
$$;"""


class HierarchicalGridSQLRegistryIJ(HierarchicalGridSQLRegistry):
    """SQL function registry for the IJ cell encoding.

    Registers a ``cell_to_parent(BIGINT, INT) RETURNS BIGINT`` function
    that coarsens an IJ-encoded 64-bit cell identifier.

    Bit layout of a cell ID:

    +-----------+---------+------------------------------------------+
    | Bits      | Field   | Notes                                    |
    +===========+=========+==========================================+
    | 63 – 58   | level   | 6 bits                                   |
    +-----------+---------+------------------------------------------+
    | 57 – 29   | i       | 29 bits (column)                         |
    +-----------+---------+------------------------------------------+
    | 28 –  0   | j       | 29 bits (row)                            |
    +-----------+---------+------------------------------------------+

    ``536870911 = 0x1FFFFFFF = 2^29 - 1`` masks a single 29-bit field.

    Coarsening right-shifts ``i`` and ``j`` independently by
    ``(child_level - parent_level)`` bits, then re-packs them with the new
    level tag — no interleaving overhead.

    Matches the Python implementation in :class:`HierarchicalGridIndexIJ`.
    """

    def get_cell_to_parent_sql(self) -> str:
        return f"""\
CREATE OR REPLACE FUNCTION {self.function_name}(cell BIGINT, parent_level INT)
RETURNS BIGINT LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE
SET search_path = public AS $$
    -- IJ encoding: bits 63-58 = level, bits 57-29 = i (29 bits), bits 28-0 = j (29 bits).
    -- Coarsen by right-shifting i and j each by (child_level - parent_level), then re-pack.
    -- 536870911 = 0x1FFFFFFF = 2^29 - 1  (mask for a single 29-bit coordinate field)
    SELECT (parent_level::BIGINT << 58)
         | ((((cell >> 29) & 536870911::BIGINT) >> ((cell >> 58)::INT - parent_level)) << 29)
         | ((cell & 536870911::BIGINT) >> ((cell >> 58)::INT - parent_level))
$$;"""


def create_patch_tables(conn, if_not_exists: bool = False) -> None:
    """Create the ``patch`` and ``pred_patch`` tables in the connected database.

    Both tables are plain PostgreSQL tables (no TimescaleDB hypertable).
    ``grid_cell_id`` in ``pred_patch`` is a ``BIGINT`` wide enough to hold
    either the 64-bit Z-order (Morton) or IJ encoded cell index produced by
    :class:`HierarchicalGridIndexZOrder` / :class:`HierarchicalGridIndexIJ`.

    Args:
        conn:          An open ``psycopg2`` connection.
        if_not_exists: When ``True``, use ``CREATE TABLE IF NOT EXISTS`` so the
                       call is a no-op when the tables already exist.
                       When ``False`` (default), raise an error if either table
                       is already present.
    """
    qualifier = "IF NOT EXISTS" if if_not_exists else ""
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE {qualifier} patch (
                id          BIGSERIAL   PRIMARY KEY,
                patch_uid   INT         NOT NULL UNIQUE,
                gt_label    INT,
                event_ts    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                image_id    INT,
                working_mag FLOAT
            );
        """)
        cur.execute(f"""
            CREATE TABLE {qualifier} pred_patch (
                id           BIGSERIAL   PRIMARY KEY,
                patch_uid    BIGINT      NOT NULL,
                embed_coords POINT,
                grid_cell_id BIGINT,
                event_ts     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                pred_label   INT,
                patch_coords POINT
            );
        """)
    if not conn.autocommit:
        conn.commit()