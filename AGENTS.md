# PatchSorter Development Guidelines for AI Agents

## Project Overview
This is a Python-based histologic object labeling tool called PatchSorter. The project uses Python 3.11+ and primarily focuses on database operations, image processing, and spatial data handling.

## Project Structure
- `patchsorter/` - Main package directory (currently empty)
- `prototyping/` - Prototype code and scripts including:
  - `table_seeding.py` - Database table seeding utilities
  - `populate_db.py` - Database population scripts
  - `utils.py` - General utility functions
  - `tile_server_prototype/` - Tile server prototype with:
    - `tile_server.py` - Main tile server implementation
    - `utils.py` - Tile server utilities
- `docs/` - Documentation files
- `LICENSE.txt` - License information
- `pyproject.toml` - Project configuration and dependencies
- `setup.py` - Setup script

## Build Commands
- `pip install -e .` - Install the package in development mode
- `python setup.py develop` - Alternative method to install in development mode

## Linting & Formatting
- No specific linting or formatting rules found in project configuration
- Code style should follow Python PEP 8 guidelines
- Type hints should be used where appropriate
- Import ordering: standard library, third-party, local imports (separated by blank lines)

## Testing
- No explicit test commands defined in pyproject.toml
- Tests can be run with `pytest` if installed
- For running a single test: `pytest path/to/test_file.py::test_function_name`
- The project uses pytest configuration from pyproject.toml with `-v` flag enabled

## Code Style Guidelines
### Imports
- Standard library imports first
- Third-party imports second
- Local application imports third
- Separate each group with a blank line
- Use `import` not `from import` when possible for better namespace management

### Naming Conventions
- Variables and functions: snake_case
- Classes: PascalCase
- Constants: UPPER_CASE
- Private methods: _private_method (leading underscore)
- Protected methods: _protected_method (single leading underscore)

### Type Hints
- Use type hints for function parameters and return values when appropriate
- Use Optional types for nullable parameters
- Use Union types for multiple possible types

### Error Handling
- Use try/except blocks for handling expected errors
- Prefer specific exceptions over generic ones
- Log errors appropriately with meaningful messages
- Don't suppress exceptions without good reason

### Documentation
- Docstrings should follow Google-style or NumPy-style conventions
- Function docstrings should include parameters, return values, and exceptions
- Class docstrings should describe the class purpose and usage

## Database Integration
The codebase uses PostgreSQL with psycopg2-binary for database operations.
- Connection handling: Use context managers where appropriate
- SQL injection prevention: Use parameterized queries
- Transaction management: Explicit commit/rollback when needed

## Special Considerations
- The project includes spatial data processing with geoalchemy2
- Uses SQLAlchemy ORM for database interactions
- Implements PostgreSQL-specific features like materialized views and functions
- Includes hierarchical grid indexing for spatial operations (Z-order and IJ encodings)