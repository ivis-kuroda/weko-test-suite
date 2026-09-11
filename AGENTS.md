# AGENTS.md

Entry point for AI agents working in this repository. Read this first.

## What this repository is

The plugin and specifications for testing WEKO3, consumed by
`agentic-test-hub`. The hub is generic and knows nothing about WEKO3;
everything specific to it lives here.

Read the hub's `AGENTS.md`, `docs/ARCHITECTURE.md` and `docs/SPEC-MODEL.md`
before changing anything structural. The data model is defined there.

## Division of responsibility

Something belongs here if it would make no sense for a different
application: a selector, a table name, a container name, a management command,
an environment variable, the organisation's delivery format.

Something belongs in the hub if it would: a new evidence channel, a new
executor, a change to how coverage is computed.

When in doubt, put it here. Moving knowledge out of the hub later is easy;
discovering that the hub only works for one application is not.

## Language rules

Same as the hub: source and code comments in English, TSDoc on exports
mandatory, agent-facing documents in English, human-facing documents in
Japanese. Specification content is written in whatever language the
specification authors use — for this target, Japanese.

## What the target actually is

WEKO3 is repository software for publishing research output. Closer to a web
database application than to a source-code repository.

| | |
|---|---|
| Backend | Invenio 3 on Flask 1.0.4, Python 3.6 |
| Frontend | React, AngularJS and jQuery, mixed by era |
| Database | PostgreSQL 12, fronted by Pgpool-II |
| Search | Elasticsearch 6.8.23 |
| Cache and session | Redis |
| Queue | RabbitMQ with Celery |
| Web server | nginx |
| Authentication | local accounts and Shibboleth |
| Deployment | docker-compose |

## Hazards worth knowing before writing a test

These are the things that make integration tests against this target fail for
reasons unrelated to the behaviour under test. Each one costs hours the first
time it is met.

**Older screens carry no stable selectors.** The AngularJS and jQuery parts of
the interface were not written with automation in mind. Adding `data-testid`
attributes to the target, screen by screen as those screens get automated, is
part of the work rather than a prerequisite for it. Keep selectors in
`plugin.yaml` operations, never in a specification, so that one attribute
change is one edit.

**Shibboleth authentication is hard to drive.** Use a local account path in
test environments and reuse a saved session rather than signing in per case.

**Indexing is asynchronous.** An item is written, then Celery indexes it.
Refreshing the search index directly is not enough, because the application's
own work may not have finished. Assert with retries, never with a fixed sleep.

**Search writes are not immediately visible.** Elasticsearch needs
`?refresh=wait_for` or an explicit refresh. Omitting it produces a test that
fails occasionally, which is the most expensive kind.

**Talk to the search cluster over REST, not through a client library.** The
official clients refuse servers outside a narrow version range, which would
pin this suite to one server major and break it at the next upgrade.

**Never point the suite at the application's own Elasticsearch instance.** Use
a separate one. A test that wipes an index is routine; doing it to real data is
not.

## Conventions for specifications

Identifiers are permanent. An entity that is removed takes its identifier with
it; nothing is renumbered or reused, because run results and bug references
point at them.

| Prefix | Entity |
|---|---|
| `VP-` | viewpoint |
| `F-` / `L-` | factor / level |
| `MX-` | matrix |
| `BL-` | baseline |
| `OP-` | operation |
| `TC-` | case |
| `SC-` / `S-` | scenario / step |

States are dotted lower-case names describing a condition, not a procedure:
`db.item_type_mapping.pristine`, not `run_the_migration_tool`.

Record the commit of `weko` a specification was written against in
`appliesTo.commit`. The existing spreadsheets already do this; keep it.
