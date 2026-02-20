import psycopg2
import math  
from typing import Tuple, List, Union  
from abc import ABC, abstractmethod

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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_level(self, cell: int) -> int:
        """Extract resolution level from encoded cell index."""
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

