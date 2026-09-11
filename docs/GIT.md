# Git workflow

Conventions and hard rules for commits and other git operations in this
repository. Everyone working here — AI agents included — follows them.

## Branching model

The target model is Git-Flow. **Until the project cuts real releases it uses
GitHub Flow instead**: `main` plus short-lived branches merged into it. There
is no `develop`, `release` or `hotfix` branch yet.

Once releases begin, switch to:

- `main` — always production-ready. Every commit is a release, tagged `vX.Y.Z`.
- `develop` — integration branch for work heading into the next release.
- `feature/<name>` — from `develop`, back into `develop`. Never straight into
  `main`.
- `release/<version>` — from `develop` when preparing a release. Version bump,
  docs and final fixes only, no new features. Merged into `main` (tagged) and
  back into `develop`.
- `hotfix/<name>` — from `main` for an urgent production fix. Merged into
  `main` (tagged) and `develop`.

Supporting branches are short-lived and deleted after merging. Never commit
directly to `main` or `develop` once the Git-Flow model is in effect.

## Review before committing

The baseline rule is that a commit is never created unilaterally: the exact
staged diff and the exact final commit message are shown and explicitly
approved before the commit exists. Agreement that "committing is the next
step" is not approval of a particular diff.

**This repository operates under an explicit waiver of that rule.** The
project owner has opted into fast autonomous development and asked to review
only material decisions. So: commit routine work without prior approval, keep
commits small and reviewable after the fact, and still surface material
decisions (data-model changes, new dependencies, reversals of documented
decisions) before acting on them.

The waiver covers routine implementation. It does not cover rewriting shared
history — see below.

## Amending versus new commits

Prefer a new commit. Amend only when explicitly asked, and only for a commit
that has not been pushed anywhere shared. Never rewrite history that others
may have pulled.

## Commit granularity

Commit finely. One commit does one thing, and its message can describe that
thing without the word "and". A commit that touches the schema, the exporter
and the docs is three commits.

## Commit message format

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

- `type` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, `revert`.
- Before choosing a `type` or `scope`, check precedent for the area with
  `git log --oneline -- <path>` and match it.
- `description` is imperative, lower-case, with no trailing period — for
  example `feat(core): add matrix derivation`.
- `body`, when present, is a concise bullet list of what changed and why —
  not prose. Each bullet follows the description's style: lower-case unless
  the first word is a proper noun, no trailing period.
- Mark a breaking change with `!` after the type or scope (`feat!: ...`) or a
  `BREAKING CHANGE:` footer. Use both only when it genuinely helps.
- `scope` is optional; use the affected package once one applies, such as
  `fix(specs): ...` or `fix(plugin): ...`.
- Any commit an AI agent contributed to carries a `Co-Authored-By` trailer
  identifying the agent.
