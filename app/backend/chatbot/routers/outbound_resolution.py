async def route(task_key: str) -> None:
    """Fan out from a completed outbound task. Real impl lands in Batch 3b."""
    # TODO(batch-3b): read ledger, dispatch to channel handler + coordinator under lock.
    return
