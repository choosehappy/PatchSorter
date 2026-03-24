# Agent Guidelines for PatchSorter Repository

## Build/Lint/Test Commands

### General Setup
- Python version: 3.8+
- Required packages: torch, numpy, pandas, scikit-learn, opencv-python, matplotlib, seaborn
- Install with: `pip install -r requirements.txt` (if exists) or individual package installation

### Linting and Formatting
- Code style: PEP 8 compliant
- Formatter: ruff (configured for Python)
- Run linter: `ruff check .`
- Auto-format code: `ruff format .`
- Type checking: mypy (run with `mypy .`)

### Testing
- Test framework: pytest
- Run all tests: `pytest`
- Run single test file: `pytest path/to/test_file.py`
- Run specific test function: `pytest path/to/test_file.py::test_function_name`
- Run with coverage: `pytest --cov=src`

## Code Style Guidelines

### Imports and Structure
- Standard library imports first, then third-party, then local imports (separated by blank lines)
- Use absolute imports when possible
- Import modules, not individual functions from modules unless necessary
- Always use `from __future__ import annotations` for forward references
- Avoid wildcard imports (`import *`)
- Group related imports together

### Naming Conventions
- Variables and functions: snake_case
- Classes: PascalCase
- Constants: UPPER_CASE
- Private methods/attributes: _private_method_name (single underscore)
- Protected attributes: __protected_attr (double underscore)

### Type Hints and Annotations
- Use type hints for all function parameters, return values, and variables where possible
- Prefer `typing.List`, `typing.Dict` over built-in types like `list`, `dict`
- Use Union types for optional parameters (e.g., `Union[int, None]` or `Optional[int]`)
- For complex types, use typing aliases

### Error Handling
- Use specific exceptions when possible instead of generic Exception
- Always document what exceptions a function can raise in docstrings
- Handle errors gracefully without suppressing them silently
- Log meaningful error messages with context information

### Documentation and Comments
- Docstrings for all public functions, classes, modules using Google-style or NumPy style
- Inline comments should explain "why" not "what"
- Avoid redundant comments that simply restate the code
- Use type hints to reduce need for inline comments on variable types

## Cursor/Copilot Rules

### Code Generation Preferences
- Prefer clear, readable Python code over clever one-liners
- When implementing machine learning models, prioritize reproducibility and documentation
- For data processing functions, include input validation and error handling
- Use appropriate logging instead of print statements for debugging

### Best Practices
- All new functionality should be tested with pytest
- Maintain consistent naming across the codebase
- Follow existing code patterns when implementing similar features
- Ensure compatibility with Python 3.8+ requirements

## Development Workflow

1. Create feature branches from main branch
2. Run linter and type checker before committing: `ruff check . && mypy .`
3. Ensure all tests pass: `pytest`
4. Add unit tests for new functionality
5. Follow PEP 8 style guide with ruff formatting
6. Write meaningful commit messages that explain the "why" of changes

## Code Review Guidelines

- Check code follows established patterns in the repository
- Verify type hints are present and correct
- Ensure error handling is appropriate for the context
- Confirm tests cover edge cases and main functionality
- Validate that linter and formatter rules are followed