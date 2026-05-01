"""Textual 4-tab TUI for the smoke harness.

Tabs:
- Customer: type as the customer; bot replies stream in.
- Vendor: every vendor-bound ping the agent dispatches lands here, tagged
  by task_key. Pick a task with `/select <task_key prefix>` (the most
  recent task is auto-selected) and type as the vendor.
- Logistics: same as Vendor, but for logistics-bound tasks.
- System: read-only firehose of logs from the orchestrator, outbound
  pipeline, resolution router, and sweeper.

Same backend as production — this only swaps WhatsApp for ConsoleChannel.
The party split is driven by ChannelIdentity.channel_user_id, which the
outbound dispatcher sets to the literal `party` string ("vendor" or
"logistics") when targeting an external party.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog, Static, TabbedContent, TabPane

from backend.chatbot import orchestrator
from backend.chatbot.agents import outbound
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage

from backend.chatbot.channels.console import ConsoleChannel
from cli import system_log
from cli.seed import ensure_smoke_data

# Disable logfire's console output — the TUI's RichLog occupies the terminal,
# so structured span output would clobber the layout. Stdlib `logger.info`
# calls still reach the System pane via cli/system_log.py.
import os as _os
_os.environ.setdefault("LOGFIRE_CONSOLE", "0")
from backend.observability import setup as setup_observability  # noqa: E402

# Wire pydantic_ai tracing before any agent module pulls Agent objects up,
# so every run executed under the smoke TUI ships spans to Logfire (cloud,
# if LOGFIRE_TOKEN is set; otherwise spans are dropped after processing).
setup_observability()


CUSTOMER_TAB = "customer"
VENDOR_TAB = "vendor"
LOGISTICS_TAB = "logistics"
SYSTEM_TAB = "system"

# Map party label → (tab id, log widget id, status widget id, input widget id).
# The dispatcher writes the literal `party` string into channel_user_id, so
# the demuxer just looks it up here.
_PARTY_PANES: dict[str, tuple[str, str, str, str]] = {
    "vendor": (VENDOR_TAB, "vendor-log", "vendor-status", "vendor-input"),
    "logistics": (LOGISTICS_TAB, "logistics-log", "logistics-status", "logistics-input"),
}


class SmokeApp(App):
    """4-tab interactive driver for the production agent stack."""

    CSS = """
    Screen { layout: vertical; }
    TabbedContent { height: 1fr; }
    RichLog { border: solid $primary; height: 1fr; }
    Input { dock: bottom; }
    .party-status { color: $accent; padding: 0 1; }
    """

    # Most terminal emulators do NOT send distinct codes for ctrl+<digit>
    # (iTerm/Terminal.app collapse them with the bare digit), so we use F-keys
    # for tab navigation and bind quit with priority=True so it wins even
    # while an Input has focus.
    BINDINGS = [
        Binding("f1", "show_tab('customer')", "Customer", show=True),
        Binding("f2", "show_tab('vendor')", "Vendor", show=True),
        Binding("f3", "show_tab('logistics')", "Logistics", show=True),
        Binding("f4", "show_tab('system')", "System", show=True),
        Binding("ctrl+right", "next_tab", "Next tab", show=True),
        Binding("ctrl+left", "prev_tab", "Prev tab", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True, priority=True),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    _TAB_ORDER = (CUSTOMER_TAB, VENDOR_TAB, LOGISTICS_TAB, SYSTEM_TAB)

    def __init__(self, business_id: str, customer_id: str) -> None:
        super().__init__()
        self.business_id = str(UUID(business_id))
        self.customer_id = str(UUID(customer_id))
        self.customer_address = f"customer-{self.customer_id[:8]}"

        self.channel: ConsoleChannel = registry.get("console")  # type: ignore[assignment]
        self._tasks: list[asyncio.Task] = []
        self._log_handler: logging.Handler | None = None
        self._system_queue: asyncio.Queue[str] = asyncio.Queue()

        # Per-party selected task + known tasks. Keys are party labels
        # ("vendor" / "logistics"); values are task_key (str) or
        # task_key → party-address dict.
        self.selected_task_key: dict[str, str | None] = {
            "vendor": None,
            "logistics": None,
        }
        self.known_task_keys: dict[str, dict[str, str]] = {
            "vendor": {},
            "logistics": {},
        }

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial=CUSTOMER_TAB):
            with TabPane("Customer", id=CUSTOMER_TAB):
                yield RichLog(id="customer-log", wrap=True, markup=True)
                yield Input(placeholder="Type as customer…", id="customer-input")
            with TabPane("Vendor", id=VENDOR_TAB):
                yield Static(
                    "No active vendor task.",
                    id="vendor-status",
                    classes="party-status",
                )
                yield RichLog(id="vendor-log", wrap=True, markup=True)
                yield Input(
                    placeholder="Reply as vendor (or /select <task_key>, /list)…",
                    id="vendor-input",
                )
            with TabPane("Logistics", id=LOGISTICS_TAB):
                yield Static(
                    "No active logistics task.",
                    id="logistics-status",
                    classes="party-status",
                )
                yield RichLog(id="logistics-log", wrap=True, markup=True)
                yield Input(
                    placeholder="Reply as logistics (or /select <task_key>, /list)…",
                    id="logistics-input",
                )
            with TabPane("System", id=SYSTEM_TAB):
                yield RichLog(id="system-log", wrap=True, markup=True)
        yield Footer()

    # -- lifecycle ------------------------------------------------------------

    async def on_mount(self) -> None:
        loop = asyncio.get_running_loop()
        self._log_handler = system_log.install(self._system_queue, loop)

        self._tasks.append(asyncio.create_task(self._drain_outbox()))
        self._tasks.append(asyncio.create_task(self._drain_system()))

        self._log("system-log", "[dim]Smoke harness up. Same agent, different transport.[/dim]")
        self._log(
            "system-log",
            f"[dim]business_id={self.business_id} customer_id={self.customer_id}[/dim]",
        )

    async def on_unmount(self) -> None:
        for w in self._tasks:
            w.cancel()
        for w in self._tasks:
            try:
                await w
            except (asyncio.CancelledError, Exception):
                pass
        if self._log_handler is not None:
            for name in (
                "backend.chatbot",
                "backend.chatbot.orchestrator",
                "backend.chatbot.routers.outbound_resolution",
                "backend.chatbot.sweeper",
            ):
                logging.getLogger(name).removeHandler(self._log_handler)

    # -- workers --------------------------------------------------------------

    async def _drain_outbox(self) -> None:
        """Demux ConsoleChannel.outbox into the Customer / Vendor / Logistics panes."""
        while True:
            identity, text = await self.channel.outbox.get()
            if identity.channel_user_id == self.customer_address:
                self._log("customer-log", f"[bold cyan]bot →[/bold cyan] {text}")
                continue

            party = identity.channel_user_id
            pane = _PARTY_PANES.get(party)
            if pane is None:
                # Unknown party — surface in System so messages aren't lost.
                self._log(
                    "system-log",
                    f"[yellow]outbound to unknown party {party!r}: {text}[/yellow]",
                )
                continue
            tab_id, log_id, _status_id, _input_id = pane

            task_key = self._parse_task_key(text)
            if task_key:
                self.known_task_keys[party][task_key] = party
                if self.selected_task_key[party] != task_key:
                    self.selected_task_key[party] = task_key
                    self._update_party_status(party)
            self._log(
                log_id,
                f"[bold magenta]agent → {party}[/bold magenta] "
                f"{'[dim](task ' + task_key[:8] + ')[/dim]' if task_key else ''}\n{text}",
            )

    async def _drain_system(self) -> None:
        while True:
            line = await self._system_queue.get()
            self._log("system-log", line)

    # -- input handlers -------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""
        if event.input.id == "customer-input":
            await self._send_as_customer(text)
        elif event.input.id == "vendor-input":
            await self._send_as_party("vendor", text)
        elif event.input.id == "logistics-input":
            await self._send_as_party("logistics", text)

    async def _send_as_customer(self, text: str) -> None:
        self._log("customer-log", f"[bold green]you →[/bold green] {text}")
        self._log("customer-log", "[dim italic]agent thinking…[/dim italic]")
        msg = InboundMessage(
            identity=ChannelIdentity(
                business_id=self.business_id,
                customer_id=self.customer_id,
                channel="console",
                channel_user_id=self.customer_address,
                last_inbound_at=datetime.now(timezone.utc),
            ),
            text=text,
            media=[],
            raw={"source": "smoke_tui"},
            received_at=datetime.now(timezone.utc),
        )
        # Fire-and-forget: an LLM round-trip can take 30s+. Awaiting it inside
        # the input handler pins the coroutine, makes the TUI feel frozen, and
        # eats subsequent keystrokes. The orchestrator's per-customer lock
        # already serializes concurrent turns, so it is safe to dispatch.
        self._tasks.append(
            asyncio.create_task(self._run_orchestrator(msg), name="orchestrator-turn")
        )

    async def _run_orchestrator(self, msg: InboundMessage) -> None:
        # Re-seed before every turn. The docker `ottobiz-backend` container
        # runs uvicorn --reload and on every reload re-runs populate.py,
        # which TRUNCATEs `businesses` and `users` CASCADE — wiping our
        # seeded rows mid-session. Re-seed is idempotent (ON CONFLICT DO
        # NOTHING / NOT EXISTS) so this is cheap and bulletproof.
        await self._reseed()
        try:
            await orchestrator.handle_inbound(msg)
        except Exception as exc:
            self._log("customer-log", f"[red]✗ orchestrator error: {exc}[/red]")
        finally:
            self._reap_tasks()

    async def _reseed(self) -> None:
        try:
            await ensure_smoke_data(self.business_id, self.customer_id)
        except Exception as exc:
            # Log but don't block the turn — the next call may still succeed
            # if the failure was transient.
            self._log("system-log", f"[yellow]reseed failed: {exc}[/yellow]")

    async def _send_as_party(self, party: str, text: str) -> None:
        log_id = _PARTY_PANES[party][1]

        if text.startswith("/select "):
            self._select_task(party, text.removeprefix("/select ").strip())
            return
        if text == "/list":
            self._show_known_tasks(party)
            return

        selected = self.selected_task_key[party]
        if not selected:
            self._log(
                log_id,
                f"[red]No outbound {party} task selected. Use /select <task_key prefix> "
                "or wait for the agent to dispatch one.[/red]",
            )
            return

        self._log(
            log_id,
            f"[bold yellow]you ({party}) →[/bold yellow] {text}  "
            f"[dim](task {selected[:8]})[/dim]",
        )
        self._log(log_id, "[dim italic]outbound agent thinking…[/dim italic]")
        # Fire-and-forget for the same reason as customer turns — the outbound
        # agent does its own LLM round-trip per party reply.
        self._tasks.append(
            asyncio.create_task(
                self._run_party_reply(selected, text, log_id),
                name="party-reply",
            )
        )

    async def _run_party_reply(self, task_key: str, text: str, log_id: str) -> None:
        # Same defensive re-seed as customer turns — see _run_orchestrator.
        await self._reseed()
        # The new outbound flow is per-contact, not per-task — translate the
        # operator's task_key selection into the contact_id behind that task,
        # then deliver as a coalesced contact reply (single-message list since
        # the TUI sends one inbound at a time).
        from backend.db import outbound_ledger as _ledger

        task = await _ledger.get_by_key(task_key)
        if task is None or task.contact_id is None:
            self._log(
                log_id,
                f"[yellow]ℹ task {task_key[:8]} has no contact bound[/yellow]",
            )
            self._reap_tasks()
            return
        try:
            status = await outbound.deliver_contact_reply(
                task.business_id, task.contact_id, [text]
            )
        except Exception as exc:
            self._log(log_id, f"[red]✗ deliver_contact_reply error: {exc}[/red]")
        else:
            if status:
                # Unknown contact / cross-tenant / send failed. Surface the
                # message so the operator knows why nothing came back instead
                # of staring at a frozen "thinking…" line.
                self._log(log_id, f"[yellow]ℹ {status}[/yellow]")
        finally:
            self._reap_tasks()

    def _reap_tasks(self) -> None:
        # Drop completed turns so the list doesn't grow forever; on_unmount
        # still cancels anything still running.
        self._tasks = [t for t in self._tasks if not t.done()]

    # -- helpers --------------------------------------------------------------

    def _select_task(self, party: str, prefix: str) -> None:
        log_id = _PARTY_PANES[party][1]
        matches = [k for k in self.known_task_keys[party] if k.startswith(prefix)]
        if not matches:
            self._log(log_id, f"[red]No open {party} task matches '{prefix}'.[/red]")
            return
        if len(matches) > 1:
            self._log(
                log_id,
                f"[red]Ambiguous prefix '{prefix}': {', '.join(m[:8] for m in matches)}.[/red]",
            )
            return
        self.selected_task_key[party] = matches[0]
        self._update_party_status(party)

    def _show_known_tasks(self, party: str) -> None:
        log_id = _PARTY_PANES[party][1]
        known = self.known_task_keys[party]
        if not known:
            self._log(log_id, f"[dim]No {party} tasks dispatched yet.[/dim]")
            return
        selected = self.selected_task_key[party]
        for task_key in known:
            marker = "→" if task_key == selected else " "
            self._log(log_id, f"  {marker} {task_key[:8]}")

    def _update_party_status(self, party: str) -> None:
        status_id = _PARTY_PANES[party][2]
        try:
            status = self.query_one(f"#{status_id}", Static)
        except Exception:
            return
        selected = self.selected_task_key[party]
        if not selected:
            status.update(f"No active {party} task.")
            return
        open_count = len(self.known_task_keys[party])
        status.update(
            f"Selected: task={selected[:8]}  party={party}  (open={open_count})"
        )

    @staticmethod
    def _parse_task_key(text: str) -> str | None:
        # Mirrors `dispatcher.dispatch_to_party` which appends "\n\n[Ref: <task_key>]".
        marker = "[Ref: "
        idx = text.rfind(marker)
        if idx == -1:
            return None
        end = text.find("]", idx)
        if end == -1:
            return None
        return text[idx + len(marker) : end]

    def _log(self, log_id: str, line: str) -> None:
        try:
            self.query_one(f"#{log_id}", RichLog).write(line)
        except Exception:
            # Widget not yet mounted — ignore.
            pass

    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_next_tab(self) -> None:
        self._cycle_tab(+1)

    def action_prev_tab(self) -> None:
        self._cycle_tab(-1)

    def _cycle_tab(self, delta: int) -> None:
        tabs = self.query_one(TabbedContent)
        try:
            idx = self._TAB_ORDER.index(tabs.active)
        except ValueError:
            idx = 0
        tabs.active = self._TAB_ORDER[(idx + delta) % len(self._TAB_ORDER)]
