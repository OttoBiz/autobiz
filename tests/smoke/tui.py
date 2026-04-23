"""Textual 3-tab TUI for the smoke harness.

Tabs:
- Customer: type as the customer; bot replies stream in.
- Outbound: every vendor/logistics ping the agent dispatches lands here,
  tagged by task_key. Pick a task with `/select <task_key prefix>` (the
  most recent task is auto-selected) and type as that party.
- System: read-only firehose of logs from the orchestrator, outbound
  pipeline, resolution router, and sweeper.

Same backend as production — this only swaps WhatsApp for ConsoleChannel.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, RichLog, Static, TabbedContent, TabPane

from backend.chatbot import orchestrator
from backend.chatbot.agents import outbound
from backend.chatbot.channels import registry
from backend.chatbot.channels.base import ChannelIdentity, InboundMessage

from tests.smoke import system_log
from tests.smoke.console_channel import ConsoleChannel


CUSTOMER_TAB = "customer"
OUTBOUND_TAB = "outbound"
SYSTEM_TAB = "system"


class SmokeApp(App):
    """3-tab interactive driver for the production agent stack."""

    CSS = """
    Screen { layout: vertical; }
    TabbedContent { height: 1fr; }
    RichLog { border: solid $primary; height: 1fr; }
    Input { dock: bottom; }
    #outbound-status { color: $accent; padding: 0 1; }
    """

    BINDINGS = [
        Binding("ctrl+1", "show_tab('customer')", "Customer", show=True),
        Binding("ctrl+2", "show_tab('outbound')", "Outbound", show=True),
        Binding("ctrl+3", "show_tab('system')", "System", show=True),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, business_id: str, customer_id: str) -> None:
        super().__init__()
        self.business_id = str(UUID(business_id))
        self.customer_id = str(UUID(customer_id))
        # The "phone number" we use for the customer in the channel identity.
        # Anything else that ConsoleChannel.send hits is a vendor/logistics party.
        self.customer_address = f"customer-{self.customer_id[:8]}"

        self.channel: ConsoleChannel = registry.get("console")  # type: ignore[assignment]
        self._workers: list[asyncio.Task] = []
        self._log_handler: logging.Handler | None = None
        self._system_queue: asyncio.Queue[str] = asyncio.Queue()

        # Selected outbound task for the Outbound tab. Auto-tracks whichever
        # task most recently produced a vendor-bound message.
        self.selected_task_key: str | None = None
        # Track every task_key we've seen on the outbox so /select can
        # auto-complete a partial prefix.
        self.known_task_keys: dict[str, str] = {}  # task_key -> party address

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial=CUSTOMER_TAB):
            with TabPane("Customer", id=CUSTOMER_TAB):
                yield RichLog(id="customer-log", wrap=True, markup=True)
                yield Input(placeholder="Type as customer…", id="customer-input")
            with TabPane("Outbound (Vendor / Logistics)", id=OUTBOUND_TAB):
                yield Static("No active outbound task.", id="outbound-status")
                yield RichLog(id="outbound-log", wrap=True, markup=True)
                yield Input(
                    placeholder="Reply as the selected party (or /select <task_key>)…",
                    id="outbound-input",
                )
            with TabPane("System", id=SYSTEM_TAB):
                yield RichLog(id="system-log", wrap=True, markup=True)
        yield Footer()

    # -- lifecycle ------------------------------------------------------------

    async def on_mount(self) -> None:
        loop = asyncio.get_running_loop()
        self._log_handler = system_log.install(self._system_queue, loop)

        self._workers.append(asyncio.create_task(self._drain_outbox()))
        self._workers.append(asyncio.create_task(self._drain_system()))

        self._log("system-log", "[dim]Smoke harness up. Same agent, different transport.[/dim]")
        self._log(
            "system-log",
            f"[dim]business_id={self.business_id} customer_id={self.customer_id}[/dim]",
        )

    async def on_unmount(self) -> None:
        for w in self._workers:
            w.cancel()
        for w in self._workers:
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
        """Demux ConsoleChannel.outbox into the Customer / Outbound panes."""
        while True:
            identity, text = await self.channel.outbox.get()
            if identity.channel_user_id == self.customer_address:
                self._log("customer-log", f"[bold cyan]bot →[/bold cyan] {text}")
            else:
                # Vendor/logistics-bound. The dispatcher appends "\n\n[Ref: <task_key>]".
                task_key = self._parse_task_key(text)
                party = identity.channel_user_id
                if task_key:
                    self.known_task_keys[task_key] = party
                    if self.selected_task_key != task_key:
                        self.selected_task_key = task_key
                        self._update_outbound_status()
                self._log(
                    "outbound-log",
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
        elif event.input.id == "outbound-input":
            await self._send_as_party(text)

    async def _send_as_customer(self, text: str) -> None:
        self._log("customer-log", f"[bold green]you →[/bold green] {text}")
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
        try:
            await orchestrator.handle_inbound(msg)
        except Exception as exc:
            self._log("customer-log", f"[red]✗ orchestrator error: {exc}[/red]")

    async def _send_as_party(self, text: str) -> None:
        if text.startswith("/select "):
            self._select_task(text.removeprefix("/select ").strip())
            return
        if text == "/list":
            self._show_known_tasks()
            return

        if not self.selected_task_key:
            self._log(
                "outbound-log",
                "[red]No outbound task selected. Use /select <task_key prefix> "
                "or wait for the agent to dispatch one.[/red]",
            )
            return

        party = self.known_task_keys.get(self.selected_task_key, "<party>")
        self._log(
            "outbound-log",
            f"[bold yellow]you ({party}) →[/bold yellow] {text}  "
            f"[dim](task {self.selected_task_key[:8]})[/dim]",
        )
        try:
            await outbound.deliver_party_reply(self.selected_task_key, text)
        except Exception as exc:
            self._log("outbound-log", f"[red]✗ deliver_party_reply error: {exc}[/red]")

    # -- helpers --------------------------------------------------------------

    def _select_task(self, prefix: str) -> None:
        matches = [k for k in self.known_task_keys if k.startswith(prefix)]
        if not matches:
            self._log("outbound-log", f"[red]No open task matches '{prefix}'.[/red]")
            return
        if len(matches) > 1:
            self._log(
                "outbound-log",
                f"[red]Ambiguous prefix '{prefix}': {', '.join(m[:8] for m in matches)}.[/red]",
            )
            return
        self.selected_task_key = matches[0]
        self._update_outbound_status()

    def _show_known_tasks(self) -> None:
        if not self.known_task_keys:
            self._log("outbound-log", "[dim]No tasks dispatched yet.[/dim]")
            return
        for task_key, party in self.known_task_keys.items():
            marker = "→" if task_key == self.selected_task_key else " "
            self._log(
                "outbound-log",
                f"  {marker} {task_key[:8]}  party={party}",
            )

    def _update_outbound_status(self) -> None:
        status = self.query_one("#outbound-status", Static)
        if not self.selected_task_key:
            status.update("No active outbound task.")
            return
        party = self.known_task_keys.get(self.selected_task_key, "<unknown>")
        status.update(
            f"Selected: task={self.selected_task_key[:8]}  party={party}  "
            f"(open={len(self.known_task_keys)})"
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

    # Custom action so the binding can switch tabs cleanly.
    def action_show_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id
