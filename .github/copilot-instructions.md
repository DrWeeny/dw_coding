# Coding Guidelines for dw_open_tools

## Imports
- Always use `import module` and call functions with the module name (e.g., `module.function()`).
- Avoid relative imports.
- Avoid `import ... as ...`.
- Avoid `from ... import ...` unless strictly necessary for clarity (e.g., `in __init__ module for importing important functions from nested modules`).
- Never use `import *`.

## Naming Conventions
- Classes: Use CamelCase (e.g., `MyClass`).
- Standalone tool packages: Use CamelCase.
- Functions: Use lower_case (e.g., `my_function`).
- Typing: Prefer inline type hints (e.g., `def foo(bar: str = "")`).

## Python Version & Compatibility
- Code must be compatible with Python 3.7 if possible.
- If using features from 3.8+, provide a fallback for 3.7. If not possible, clearly indicate in the code that 3.7 is not supported.
- Do not use the walrus operator (`:=`).

## Strings & Formatting
- Always use f-strings for string formatting.

## Qt Guidelines
- Prefer PySide6 for Maya tools.
- If using a model, always implement a proxy model as well.
- Be careful: PySide6 uses enumerators for checkboxes and some widgets.
- Be careful: Python garbage collection is different from C++. Always assign new Qt items to a variable (e.g., `item = QtWidgets.QStandardItem()`).
- For Qt tools, use the following folder structure:
  - `main_ui.py` for the core UI
  - `cmds_py` for UI commands and API imports
  - `wgt_{name}.py` for sub-widgets
  - Shared widgets go in `dw_widgets`
  - For widget communication, use a singleton `dw_data_hub` and a `wgt_hub.py` base class for subwidgets
  - Place all UI commands in a `cmds_py` file to keep UI code clean
- Prefer partial module rather than lambda for signal connections.

## Documentation
- Docstrings must be in English, minimal, and follow the Google style guide.
- At the module level, provide:
  - Summary
  - Features
  - Classes
  - Functions
  - Example
  - TODO
  - Author name
  - Web documentation (if any external resource was used)

## Comments
- Use comments to explain code blocks when necessary, but avoid over-commenting.
- Code should be as self-explanatory as possible.

## Tests
- No tests are required unless explicitly requested.

## Security
- No specific security requirements for now.

---

*Last updated: 2026-04-10*

