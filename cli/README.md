# Smoke harness

A 4-tab TUI that lets you drive the **real** agent stack — same orchestrator,
same `central_agent`, same `outbound_agent`, same Redis/Postgres/ledger — from
your terminal. The only thing swapped out is the channel: `ConsoleChannel`
takes the place of WhatsApp, so every `channel.send()` lands in a TUI pane
instead of going to Meta.

You play the customer in one tab, the vendor in another, and logistics in a
third; the agent does its real thing in between. Business and customer rows
are seeded automatically at startup with deterministic UUIDs so re-running
the CLI is a no-op against existing data.

## Requirements

- **Redis** and **Postgres** running. The simplest path:

  ```bash
  cd app
  docker compose up redis postgres
  ```

- **A model provider API key.** The agents call out to whatever
  `MODEL_NAME` points at; pydantic_ai picks the matching env var. Examples:

  | `MODEL_NAME`                       | env var to set    |
  | ---------------------------------- | ----------------- |
  | `openai:gpt-4o`                    | `OPENAI_API_KEY`  |
  | `anthropic:claude-sonnet-4-5`      | `ANTHROPIC_API_KEY` |
  | `google-gla:gemini-2.0-flash`      | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |

  Either export it in your shell, or drop it into `app/.env`.

- **Textual** — installed via `app/requirements.txt`.

## Run

Interactive:

```bash
.venv/bin/python -m cli.cli
```

Override the model for one session:

```bash
.venv/bin/python -m cli.cli --model openai:gpt-4o
```

Headless scripted scenario (CI mode — populated in task #9):

```bash
.venv/bin/python -m cli.cli --scenario vendor_confirmation
```

## TUI layout

- `F1` — **Customer** tab. Type to send as the customer; bot replies stream in.
- `F2` — **Vendor** tab. Every vendor-bound message the agent dispatches
  lands here, tagged with a short `task_key`. Type to reply as the
  currently-selected vendor task.
- `F3` — **Logistics** tab. Same as Vendor but for logistics-bound tasks.
- `F4` — **System** tab. Read-only stream of orchestrator / outbound /
  resolution-router / sweeper logs.
- `Ctrl+→` / `Ctrl+←` — cycle through tabs (F-keys are unreliable on some
  terminal multiplexers; the arrow shortcuts always work).

The Vendor and Logistics tabs each support:
- `/list` — list open tasks for that party.
- `/select <task_key prefix>` — switch the active conversation.
- The most recent dispatch is auto-selected so you can usually just type.

`Ctrl+Q` (or `Ctrl+C`) exits. Both bindings are priority bindings, so they
fire even while an Input has focus.

## Why agent calls don't freeze the UI

Each customer / vendor / logistics submission is dispatched as a background
asyncio task instead of being awaited inline in the input handler. That keeps
keystrokes, tab switching, and quit responsive while the LLM round-trip
runs (often 5–30s). You'll see a `agent thinking…` line in the relevant pane
the moment you hit enter; the bot's reply lands in the same pane when it's
ready. The orchestrator's per-customer Redis lock still serializes turns, so
you can't accidentally interleave two in-flight customer messages.

## What's wired up

```
[Customer tab] ──► InboundMessage ──► orchestrator.handle_inbound
                                          │
                                          ▼
                                   central_agent (real LLM call)
                                          │
                                          ├── query_subagent → product / payment / logistics / customer_relation
                                          │
                                          └── outbound subagent → outbound.dispatch
                                                                       │
                                                                       ▼
                                                             outbound_agent (real LLM call)
                                                                       │
                                                                       ▼
                                                              ConsoleChannel.send
                                                                       │
                                                                       ▼
                                                       [Vendor tab or Logistics tab]
                                                                       │
                                                          you type as vendor/logistics
                                                                       │
                                                                       ▼
                                                       outbound.deliver_party_reply
                                                                       │
                                                                       ▼
                                                            outbound_agent continues
                                                                       │
                                                          (calls mark_completed eventually)
                                                                       │
                                                                       ▼
                                                  outbound_resolution.route → coordinator
                                                                       │
                                                                       ▼
                                              next customer turn picks up the resolution
```

The Outbound tab shows everything regardless of whether the party is "vendor"
or "logistics" — the agent picks the right party label per task; you just
play whichever role the task says.
