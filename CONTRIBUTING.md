# Contributing to ChatISP AI Backend

Thank you for your interest in contributing! This document outlines the process for contributing to the project.

## Code of Conduct

Please be respectful and constructive in all interactions.

## How to Contribute

1. **Fork** the repository.
2. **Create a branch** for your feature or bugfix: `git checkout -b feature/your-feature`.
3. **Make your changes**, ensuring code style and tests pass.
4. **Write tests** for any new functionality.
5. **Commit** with clear messages.
6. **Push** to your fork and open a **Pull Request** against the `main` branch.

## Development Setup

- Python 3.11 or higher.
- Install dependencies: `pip install -r requirements.txt`
- Install development dependencies: `pip install -e .[dev]`
- Run tests: `pytest tests/ -v`
- Format code: `black .` and `isort .`
- Type check: `mypy app/`

## Project Structure

See `README.md` for an overview.

## Pull Request Guidelines

- Keep changes focused; one PR per feature/fix.
- Update documentation if needed.
- Ensure all tests pass.
- Add a clear description of the changes.

## Reporting Issues

Use the GitHub issue tracker. Provide as much detail as possible, including steps to reproduce.

Thank you for helping improve ChatISP AI!
