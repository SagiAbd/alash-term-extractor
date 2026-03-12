# Tasks

- [ ] Add Excel field for **author summary** (`Автор туралы қысқаша мазмұн`).
- [ ] Add Excel field for **text summary** (`Мәтін туралы қысқаша мазмұн`).
- [ ] Decide summary scope:
  - author summary = one per book
  - text summary = one per page or one global summary per run
- [ ] Update `3_extract_terms.py` prompt to request both summary fields from Gemini.
- [ ] Update export column order in `3_extract_terms.py` to include new summary columns.
- [ ] If summary is book-level, write it once in metadata header block (top of Excel) and optionally duplicate in rows.
- [ ] Add fallback logic: if Gemini does not return summary, write empty string instead of failing.
- [ ] Update `README.md` output section to document new summary fields.
- [ ] Add a changelog entry after implementation.
