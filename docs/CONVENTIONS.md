# Documentation conventions

> **Summary:** Naming rules, required metadata, and standard section order for all Markdown under `docs/`. Follow this when adding or editing documentation.  
> **Updated:** 2026-05-16 · **Author:** Unidata audit team · **Status:** Ready for review

---

## File naming

Use **lowercase kebab-case** only. Pattern:

| Prefix | Use | Example |
|--------|-----|---------|
| `step-NN-` | Work-plan step guide or generated workshop output | `step-03-field-semantics.md` |
| `step-NN-…-template` | Blank workshop / ticket template | `step-04-product-field-review-template.md` |
| `release-` | Versioned dataset or snapshot record | `release-unidata-v2.3-data-sheet.md` |
| `ticket-NN-` | Ticket / issue write-up | `ticket-03-step-3-field-semantics.md` |
| `CONVENTIONS.md` | Meta (this file) | — |
| `index.md` | Documentation catalog | — |

**Rules**

- `NN` = two-digit step number (`01`–`05`).
- No underscores, spaces, or `camelCase` in filenames.
- Companion data files use the same stem: e.g. `release-unidata-v2.3-field-missingness.csv`.
- Generated files keep the same prefix as their step (`step-04-product-field-review.md`).

---

## Required header (every doc)

Immediately under the `#` title, include:

```markdown
> **Summary:** One to three sentences: what this doc is and who should read it.  
> **Updated:** YYYY-MM-DD · **Author:** Name or team · **Status:** WIP | Ready for review | Completed
```

**Status meanings**

| Status | When to use |
|--------|-------------|
| **WIP** | Draft; numbers or decisions may change |
| **Ready for review** | Content complete; awaiting stakeholder sign-off |
| **Completed** | Reviewed and current for its stated scope |

When you edit a doc, bump **Updated** and adjust **Status** if needed.

---

## Standard outline

Use these `##` sections (omit only if not applicable):

### Step guides (`step-NN-…`)

1. **Purpose** — why this step exists  
2. **Prerequisites** — DB, prior steps, artifacts  
3. **How to run** — command(s) from repo root  
4. **Outputs** — paths under `outputs/`  
5. **How to use results** — handoff to next step  
6. **Related documents** — links to `docs/index.md` entries  

### Templates (`step-NN-…-template`)

1. **Purpose**  
2. **How to use this template**  
3. **Workshop content** (tables / checklists)  
4. **Related documents**  

### Release records (`release-…`)

1. **Purpose**  
2. **Totals**  
3. **Details** (tables, process, issues)  
4. **Related documents**  

### Tickets (`ticket-NN-…`)

1. **Purpose** / background  
2. **Scope**  
3. **Acceptance criteria**  
4. **Artifacts**  
5. **Related documents**  

---

## Index and README

- Add or update every new doc in **`docs/index.md`**.
- Keep the root **`README.md`** “Documentation” section in sync (short pointer to `docs/index.md`).

---

## Related documents

- [Documentation index](index.md)
