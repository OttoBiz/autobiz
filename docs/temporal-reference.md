# Temporal Implementation Reference

**Status:** Removed - Kept for future reference

**Date Removed:** October 2025

## Why We Used Temporal

Temporal was initially implemented to provide **durable, long-running conversations** with customers. The key benefits were:

1. **Durability**: Conversations could survive server restarts
2. **Long-running workflows**: Single workflow instance per conversation (could run for days/weeks)
3. **State persistence**: Automatic state management and recovery
4. **Signal-based messaging**: New messages sent as signals to running workflows
5. **Timeout handling**: Automatic conversation archival after 30 days of inactivity

## Implementation Pattern

### Architecture Overview

```
Customer Message → Webhook → Temporal Workflow (Signal) → Activity (Agent Execution) → Response
                                     ↓
                              PostgreSQL (State)
```

### Key Components

1. **ConversationWorkflow** (`temporal/workflows/conversation.py`)
   - One workflow instance per conversation
   - Ran indefinitely, waiting for message signals
   - Timeout after 30 days of inactivity
   - Handled agent handoffs and pause/resume

2. **Activities** (`temporal/activities/`)
   - `initialize_conversation_state`: Setup new conversation
   - `execute_agent`: Run agent with state loading/saving
   - `send_message`: Send response to customer via channel
   - `archive_conversation`: Archive inactive conversations
   - `create_state_snapshot`: Snapshot state for pause/resume

3. **State Management** (`agents/state/`)
   - State stored in PostgreSQL (not workflow memory)
   - Activities loaded/saved state on each message
   - Snapshots created for pause/resume workflows

4. **Webhook Integration** (`api/routes/webhooks.py`)
   - Start new workflow for new conversations
   - Signal existing workflows for ongoing conversations

### Workflow Lifecycle

```python
# New conversation
workflow_id = f"conversation-{conversation_id}"
handle = await client.start_workflow(
    ConversationWorkflow.run,
    args=[conversation_id, business_id, agent_id, agent_role, customer_id],
    id=workflow_id,
    task_queue="autobiz-customer-service",
)

# Existing conversation
handle = client.get_workflow_handle(workflow_id)
await handle.signal(
    ConversationWorkflow.new_message,
    CustomerMessage(message="...", timestamp=..., metadata=...),
)
```

## Why We Removed It

1. **Complexity overhead**: Too much infrastructure for current stage
2. **Not fully tested**: Integration tests existed but workflow wasn't battle-tested
3. **Simple alternative available**: Direct AgentExecutor calls work fine
4. **Database sufficient**: PostgreSQL handles state persistence adequately
5. **Premature optimization**: Don't need durable workflows until we have scale issues

## What We Learned

### Good Patterns to Keep

1. **Separation of concerns**: Activities handled I/O, workflows handled orchestration
2. **State externalization**: Storing state in PostgreSQL (not workflow memory) was correct
3. **Structured outputs**: HandoffResponse, PauseResponse patterns worked well
4. **Signal-based messaging**: Clean pattern for async message delivery

### Challenges Encountered

1. **Testing complexity**: Replay testing was complex (see `scripts/test_workflow_determinism.py`)
2. **State synchronization**: Keeping workflow and database state in sync required care
3. **Deployment overhead**: Needed separate worker processes (`workers/conversation_worker.py`)
4. **Development friction**: Local Temporal server required for development

## Current Simple Implementation

Replaced with direct AgentExecutor pattern:

```python
# New webhook implementation (api/routes/webhooks.py)
executor = ProductionAgentExecutor()
response = await executor.run(
    business_id=business_id,
    conversation_id=conversation_id,
    agent_role=agent_role,
    user_message=message,
    deps=deps,
    message_history=history,
)
```

Benefits:
- No workflow orchestration needed
- Simpler deployment (no workers)
- Easier testing (standard unit tests)
- State still in PostgreSQL
- Same agent collaboration patterns work

## When to Re-implement Temporal

Consider bringing back Temporal when you need:

1. **Long-running operations**: Multi-step workflows spanning hours/days
2. **Guaranteed delivery**: Critical operations that must complete even if server crashes
3. **Complex orchestration**: Multiple external services with retries/compensation
4. **Scheduled workflows**: Recurring tasks, delayed actions
5. **Audit trail**: Built-in event history for compliance

## Files Removed

```
temporal/
├── __init__.py
├── client.py
├── models.py
├── activities/
│   ├── __init__.py
│   ├── initialization.py
│   ├── messaging.py
│   ├── agent.py
│   └── state.py
└── workflows/
    ├── __init__.py
    └── conversation.py

workers/
└── conversation_worker.py

tests/unit/
├── test_state_manager.py
├── test_state_activities.py
└── test_agent_activity.py

tests/integration/
├── test_conversation_workflow.py
└── test_workflow_replay.py

scripts/
└── test_workflow_determinism.py

tests/README.md
```

## Useful References

- [Temporal Docs](https://docs.temporal.io/)
- [Temporal Python SDK](https://github.com/temporalio/sdk-python)
- [State Management Pattern](https://docs.temporal.io/encyclopedia/workflow-state)
- Our implementation: `git log --all --grep="temporal"` to see commits

## Quick Start (if re-implementing)

```bash
# Install Temporal CLI
brew install temporal

# Start local Temporal server
temporal server start-dev

# Run worker
uv run python -m workers.conversation_worker

# Start API (will connect to Temporal)
uv run uvicorn api.main:app --reload
```

The code structure was sound - we just don't need it yet. When you do need Temporal, start with:
1. Review this document
2. Check git history for implementation (`git log --all -- temporal/`)
3. Adapt the workflow pattern to current needs
4. Add proper integration tests before deploying
