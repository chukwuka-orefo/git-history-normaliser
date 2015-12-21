# Git History Normaliser

Do you wake up in the morning and go to bed at night?

If so, you probably experience time as something that moves forward in a fairly regular way.
Most people do.

Git repositories, on the other hand, often do not.

Commits jump years into the future.
Maintenance work overwrites history.
Author dates and commit dates quietly drift apart.
What once looked like a coherent development story slowly turns into noise.

Git History Normaliser exists to make that story readable again.

Not by changing what happened.
Only by normalising *when* it appears to have happened.

---

## What this tool is (and is not)

Git History Normaliser operates on **timestamps only**.

It does not:
- change commit contents
- change commit messages
- change commit order or topology
- hide authorship
- invent or delete commits

It works by replaying an existing Git history on a controlled clock,
under a policy you define.

Think of it as the same movie, projected on a different timeline.

---

## Modes of operation

The tool supports three mutually exclusive modes:

- **Author mode**  
  Treats the original author timestamps as ground truth and aligns committer timestamps to match.

- **Commit mode**  
  Accepts committer timestamps as the canonical timeline and aligns author timestamps accordingly.

- **Synthetic mode**  
  Generates a new, human-plausible timeline within a defined calendar window,
  respecting working hours, days of the week, and realistic gaps.

Only one mode applies at a time.

---

## Policy driven

All behaviour is defined by a single YAML policy file.

The policy describes:
- which portion of history is affected
- how time should be interpreted
- when work is allowed to occur
- how much randomness is acceptable

The YAML is intentionally explicit.
It describes how a human works, not how Git works.

The web interface exists to help construct this policy.
The policy itself remains the source of truth.

---

## Using the tool

There are two primary ways to use Git History Normaliser.

### Web interface (recommended)

On Windows, the project includes a launcher:

```

start_ui.bat

```

Double-clicking it will:
- start the local web interface
- open your browser automatically
- allow you to select a repository
- preview changes before applying them

No command line interaction is required.

### Command line

For scripting or advanced usage, the tool can also be run directly:

- `main.py` for dry runs and inspection
- `synth/rewrite.py` for destructive rewrites

The command line uses the same YAML policy as the web interface.

---

## Dry runs and safety

Before any rewrite occurs, the tool can perform a **dry run**.

A dry run:
- computes final timestamps
- shows which commits would change
- leaves the repository untouched

Destructive rewrites require explicit confirmation.

---

## Installation and portability

The project is self-contained and written in pure Python.

A `requirements.txt` file is provided for users who do not use WinPython.

Example:

```

pip install -r requirements.txt

```

Releases are also provided as pre-packaged ZIP archives for convenience.

---
