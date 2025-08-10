# Improvement Plan (Windows, Offline-First)

This plan governs iterative improvements for this repository. It aligns with .junie/guidelines.md and the live Kanban embedded there.

Scope and principles:
- Windows-first. Use PowerShell-friendly commands and backslash paths.
- Offline/deterministic by default. No external network calls; zero non-stdlib dependencies unless justified.
- Minimal, incremental changes with unit tests for each improvement.
- Keep documentation current (README, docs/) and mark tasks as completed in docs/tasks.md.

Process:
1) Pick the next ready task from docs/tasks.md (respect WIP limits and Kanban in .junie/guidelines.md).
2) Implement minimal changes to satisfy acceptance criteria.
3) Add or update unit tests under tests\ (unittest, deterministic, offline).
4) Validate locally:
   - python -m unittest discover -s tests -p "test_*.py" -v
5) Update documentation:
   - README.md sections (Project Layout, CLI Usage) with Windows-style examples.
   - docs/tasks.md: change the completed task from [ ] to [x].
6) Ensure privacy-by-design and error handling per .junie/guidelines.md.

Acceptance criteria (for each task):
- All tests pass locally via the unittest command above.
- No external network calls by default; remains runnable without extra installs.
- Windows PowerShell commands in docs are correct and use backslashes.
- Where applicable, logging is stdlib logging and secrets are not printed.

Versioning & Traceability:
- Keep docs/tasks.md as the single checklist for this iteration.
- Link examples and instructions to components actually present in src\.

Notes:
- If heavy features are introduced later, prefer adding a pyproject.toml and documenting exact local run instructions.
