# docs — knowledge & records index

Domain-partitioned documentation. Each domain folder is the single source of truth
for its kind of record. Add a new kind of record by creating `docs/<domain>/` and
adding one row here.

| Domain | What lives there | Entry |
|--------|------------------|-------|
| Protocol | UDP relay + SICK MS3 wire formats | [protocol/README.md](protocol/README.md) |
| Worklog | Dated work logs (newest on top) | [worklog/](worklog/) |
| Issues & Fixes | Diagnosed bugs and their fixes | [issues_and_fixes/issues_and_fixes.md](issues_and_fixes/issues_and_fixes.md) |
| Code Updates | File-level change log | [code_updates/amr_lidar_code_updates.md](code_updates/amr_lidar_code_updates.md) |
| Analysis | Analysis / assessment reports (e.g. calibration quality) | [analysis/](analysis/) |

## Conventions
- Filenames lowercase; folder entry point is one `README.md`.
- Dates `YYYY-MM-DD`; time-ordered records are newest-on-top (reverse chronological).
- Links are relative and clickable; code blocks are language-tagged.
- Vendor manuals/specs are **not** here — they live read-only in [`../reference/`](../reference/)
  and are cited by filename + page.
- Layout philosophy and per-folder purpose: [`../DIRECTORY_GUIDE.txt`](../DIRECTORY_GUIDE.txt).
