# Nazo-Agent System: AI Coding Guidelines & Absolute Directives

## 1. Architectural SSoT (Single Source of Truth)
- **Infrastructure:** Local SQLite (`nazokake_local.db`) is the absolute source of truth. Synchronization to Firestore is strictly "One-way Push" (except for user feedback).
- **Frontend Data:** Use static JSON/JS module delivery via asynchronous `fetch()` (Lazy Loading). Never hardcode datasets into HTML.
- **UI/UX:** Adhere to Progressive Disclosure (e.g., Tailwind accordions). Maintain Mobile-First responsiveness.

## 2. Fail-Closed Principle
- **NEVER** write `try-except pass` or silent `catch (e) {}` blocks.
- All errors must be explicitly logged (audit logs/DLQ) and processes must fail safely (halt) rather than continuing in an corrupted state (Fail-Open is forbidden).

## 3. AST-Driven Surgical Patches
- Avoid ad-hoc hacks, type ignoring (e.g., `# type: ignore`, `Any` casting).
- **NEVER** reconstruct entire files using `ast.unparse()` as it destroys source code comments.
- When applying patches, locate the deterministic target node (line numbers/signatures) via `ast` and apply modifications strictly using array slice replacement (Surgical Patch).

## 4. Blast Radius Declaration
- Before proposing any code modification, you must explicitly declare the "Blast Radius" (impacted modules and files).