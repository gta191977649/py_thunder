# Changelog

All notable changes to this project will be documented in this file.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Added standalone packaging scripts for Windows, macOS, and Linux.
- Added a GitHub Actions workflow for cross-platform packaging.
- Added `requirements-build.txt` for packaging dependencies.
- Added repository-level documentation files: `LICENSE`, `CONTRIBUTING.md`, and `CHANGELOG.md`.

### Changed

- Updated runtime resource path resolution to work correctly in packaged builds.
- Rewrote `README.md` to include setup, architecture, packaging, and collaboration guidance.
- Added a practical project `.gitignore` for Python, PyInstaller, IDE files, and local artifacts.

## [0.1.0] - 2026-05-30

### Added

- Initial PyThunder MVP structure.
- PyQt6 desktop shell with classic-style layout.
- Download task table, sidebar, task details, and piece map view.
- aria2 process launcher and JSON-RPC integration.
- SQLite-based task persistence.
- Theme loading and local configuration support.
- Windows portable packaging validated locally with PyInstaller.
