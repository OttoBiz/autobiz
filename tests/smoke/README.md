# Smoke harness

A 3-tab TUI that lets you drive the **real** agent stack — same orchestrator,
same `central_agent`, same `outbound_agent`, same Redis/Postgres/ledger — from
your terminal. The only thing swapped out is the channel: `ConsoleChannel`
takes the place of WhatsApp, so every `channel.send()` lands in a TUI pane
instead of going to Meta.

You play the customer in one tab and the vendor/logistics party in another;
the agent does its real thing in between.

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
.venv/bin/python -m tests.smoke.cli
```

Override the model for one session:

```bash
.venv/bin/python -m tests.smoke.cli --model openai:gpt-4o
```

Headless scripted scenario (CI mode — populated in task #9):

```bash
.venv/bin/python -m tests.smoke.cli --scenario vendor_confirmation
```

## TUI layout

- `Ctrl+1` — **Customer** tab. Type to send as the customer; bot replies stream in.
- `Ctrl+2` — **Outbound (Vendor / Logistics)** tab. Every party-bound message
  the agent dispatches lands here, tagged with a short `task_key`. Type to
  reply as the currently-selected party.
  - `/list` lists open tasks.
  - `/select <task_key prefix>` switches the active conversation.
  - The most recent dispatch is auto-selected so you can usually just type.
- `Ctrl+3` — **System** tab. Read-only stream of orchestrator / outbound /
  resolution-router / sweeper logs.

`Ctrl+C` exits.

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
                                                              [Outbound tab]
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
