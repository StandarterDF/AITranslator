import os
import sys
import time
import queue
import subprocess
import threading
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent
os.chdir(str(ROOT))
sys.path.insert(0, str(ROOT))

log_queue: queue.Queue = queue.Queue()
event_queue: queue.Queue = queue.Queue()
stop_flag = threading.Event()


class QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%H:%M:%S'
        ))

    def emit(self, record):
        try:
            self.q.put(self.format(record))
        except Exception:
            pass


root_logger = logging.getLogger()
for h in root_logger.handlers[:]:
    root_logger.removeHandler(h)
root_logger.addHandler(QueueLogHandler(log_queue))
root_logger.setLevel(logging.INFO)

for name in ('httpx', 'httpcore'):
    logging.getLogger(name).setLevel(logging.WARNING)

import config as cfg

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, RichLog, Static, Button, Label
from textual.screen import ModalScreen
from textual.binding import Binding


class PresetSelectScreen(ModalScreen):
    BINDINGS = [
        Binding("up", "prev_button", "", show=False),
        Binding("down", "next_button", "", show=False),
    ]

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Select translation preset:", id="dlg-title")
            for key, p in cfg.PRESETS.items():
                label = f"  {p.get('name', key)}  "
                desc = p.get("description", "")
                if desc:
                    label += f"\n  [dim]{desc}[/dim]"
                yield Button(label, id=f"p{key}", variant="primary")
            yield Button("Use default (env)", id="cancel", variant="default")
            yield Label("[dim]Up/Down or Tab - navigate | Enter - select[/dim]", id="dlg-hint")

    def action_next_button(self):
        self.focus_next()

    def action_prev_button(self):
        self.focus_previous()

    def on_button_pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id.startswith("p"):
            self.dismiss(event.button.id[1:])


class ServerProcess:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._preset_key: str | None = None
        self._preset_name: str = "default"
        self.translator: Any = None

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _resolve_name(self, key: str | None) -> str:
        if not key:
            return "default"
        p = cfg.PRESETS.get(key)
        return p.get("name", key) if p else key

    def start(self, preset_key: str | None = None):
        if self.is_alive:
            return
        self._preset_key = preset_key
        self._preset_name = self._resolve_name(preset_key)
        stop_flag.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        import uvicorn
        from translator import LLMTranslator

        if self._preset_key:
            os.environ["TRANSLATOR_PRESET"] = self._preset_key
            p = cfg.load_preset(self._preset_key)
            if p:
                cfg.apply_preset(p)
        else:
            os.environ.pop("TRANSLATOR_PRESET", None)

        self.translator = LLMTranslator()

        import main as main_module
        main_module.translator = self.translator

        uvicorn_cfg = uvicorn.Config(
            "main:app",
            host="0.0.0.0",
            port=5555,
            log_level="info",
            reload=False,
            lifespan="on",
        )
        self._server = uvicorn.Server(uvicorn_cfg)

        def _watcher():
            while not stop_flag.is_set():
                time.sleep(0.3)
            if self._server:
                self._server.should_exit = True

        threading.Thread(target=_watcher, daemon=True).start()

        event_queue.put({
            "type": "status",
            "text": f"Server started ({self._preset_name})"
        })

        self._server.run()
        self._server = None

    def stop(self, timeout: float = 5.0):
        stop_flag.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None
        self._server = None

    def restart(self, preset_key: str | None = None):
        event_queue.put({"type": "status", "text": "Restarting server..."})
        self.stop()
        self.start(preset_key or self._preset_key)


server_proc = ServerProcess()


class StatusPanel(Static):
    pass


STATUS_ON = "[ ON ]"
STATUS_OFF = "[OFF]"
STATUS_WAIT = "[WAIT]"


class TranslatorTUI(App):
    CSS = """
    Screen {
        background: #0a0a0a;
    }

    *:focus {
        border: solid #888 !important;
        background: #2a2a2a !important;
    }

    #sidebar {
        width: 34;
        min-width: 30;
        border: solid #333;
        padding: 0 1;
        margin: 0 1 0 0;
        background: #141414;
    }

    #main-panel {
        height: 100%;
    }

    #log-widget {
        height: 1fr;
        border: solid #333;
        background: #0a0a0a;
    }

    #status {
        height: auto;
    }

    #stats-bar {
        height: 3;
        content-align: center middle;
        border: solid #cc7000;
        background: #1a0d00;
        color: #ff8800;
        margin: 1 0 0 0;
    }

    #dialog {
        width: 86;
        height: auto;
        padding: 1 2;
        border: thick #cc7000;
        background: #141414;
    }

    #dlg-title {
        text-align: center;
        padding: 0 0 1 0;
        text-style: bold;
        color: #ff8800;
    }

    #dlg-hint {
        text-align: center;
        padding: 1 0 0 0;
        color: #666;
    }

    #dialog Button {
        margin: 1 0;
        width: 100%;
    }

    Button {
        background: #222;
        color: #d4d4d4;
        border: solid #444;
        text-align: center;
    }

    PresetSelectScreen {
        align: center middle;
    }

    Header {
        background: #1a0d00;
        color: #ff8800;
    }

    Footer {
        background: #0a0a0a;
        color: #666;
    }

    RichLog {
        scrollbar-color: #333 #0a0a0a;
        scrollbar-size: 1 1;
    }
    """

    COLORS = {
        "primary": "#cc7000",
        "secondary": "#444",
        "accent": "#ff8800",
        "surface": "#141414",
        "panel": "#1c1c1c",
        "boost": "#1a0d00",
        "background": "#0a0a0a",
        "text": "#d4d4d4",
        "text-disabled": "#666",
        "error": "#cc3333",
        "success": "#33aa33",
    }

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
        Binding("f1", "select_preset", "Preset"),
        Binding("f2", "toggle_reasoning", "Reasoning"),
        Binding("f5", "clear_log", "Clear log"),
        Binding("f3", "restart_server", "Restart"),
        Binding("f6", "copy_logs", "Copy logs"),
    ]

    def __init__(self):
        super().__init__()
        self.msg_count = 0
        self.err_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._all_logs: list[str] = []
        self.start_time = datetime.now()
        self._current_preset_key: str | None = None
        self._current_preset_name: str = "default"
        self._server_started = False
        self._status_msg = "Waiting..."

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield StatusPanel(id="status")
                yield Static("", id="stats-bar")
            with Vertical(id="main-panel"):
                yield RichLog(id="log-widget", highlight=True, markup=True, max_lines=2000)
        yield Footer()

    def on_mount(self):
        self.push_screen(PresetSelectScreen(), self._on_preset_selected)

    def _on_preset_selected(self, key: str | None):
        if key:
            self._current_preset_key = key
            p = cfg.PRESETS.get(key, {})
            self._current_preset_name = p.get("name", key)
            label = p.get("name", key)
            desc = p.get("description", "")
            self._write_raw(f"[bold #ff8800]>> Selected: {label}[/bold #ff8800]")
            if desc:
                self._write_raw(f"[dim]   {desc}[/dim]")
        else:
            self._write_raw("[dim]Using default preset[/dim]")

        self.start_time = datetime.now()
        server_proc.start(self._current_preset_key)
        self._server_started = True
        self.set_interval(0.05, self._poll_queues)
        self.set_interval(1.0, self._periodic_update)

    def _poll_queues(self):
        log = self.query_one("#log-widget", RichLog)

        while not log_queue.empty():
            try:
                msg = log_queue.get_nowait()
                self._write_log(log, msg)
            except queue.Empty:
                break

        while not event_queue.empty():
            try:
                ev = event_queue.get_nowait()
                self._handle_event(ev)
            except queue.Empty:
                break

        self._update_tokens()

    def _update_tokens(self):
        t = server_proc.translator
        if t:
            self.prompt_tokens = t.prompt_tokens
            self.completion_tokens = t.completion_tokens

    def _write_log(self, log: RichLog, msg: str):
        self._all_logs.append(msg)
        ml = msg.lower()
        if "error" in ml or "ошибк" in ml:
            log.write(f"[#cc3333]{msg}[/#cc3333]")
        elif "warning" in ml or "предупрежд" in ml:
            log.write(f"[#ffaa33]{msg}[/#ffaa33]")
        elif "success" in ml:
            log.write(f"[bold #33aa33]{msg}[/bold #33aa33]")
            if "translat" in ml or "символов" in ml:
                self.msg_count += 1
        elif "post /translate" in ml or "get /translate" in ml:
            log.write(f"[bold #33aa33]{msg}[/bold #33aa33]")
            self.msg_count += 1
        elif "cached" in ml:
            log.write(f"[#44bbdd]{msg}[/#44bbdd]")
            if "using cached" in ml or "cache hit" in ml:
                self.msg_count += 1
        elif "uvicorn running" in ml or "startup complete" in ml or "running on" in ml:
            log.write(f"[bold #44bbdd]{msg}[/bold #44bbdd]")
        elif "application startup" in ml or "started server process" in ml:
            log.write(f"[bold #44bbdd]{msg}[/bold #44bbdd]")
        else:
            log.write(f"[#d4d4d4]{msg}[/#d4d4d4]")

        self._update_status()

    def _handle_event(self, ev: dict):
        t = ev.get("type", "")
        text = ev.get("text", "")

        if t == "status":
            self._status_msg = text
        elif t == "error":
            self.err_count += 1
            self._status_msg = f"Error: {text}"
            log = self.query_one("#log-widget", RichLog)
            if log:
                log.write(f"[bold #cc3333][!] {text}[/bold #cc3333]")

        self._update_status()

    def _update_status(self):
        uptime = str(datetime.now() - self.start_time).split(".")[0]

        if not self._server_started:
            icon = STATUS_WAIT
        elif server_proc.is_alive:
            icon = STATUS_ON
        elif "ошибк" in self._status_msg.lower() or "error" in self._status_msg.lower():
            icon = STATUS_OFF
        else:
            icon = STATUS_WAIT

        preset_name = self._current_preset_name or "default"
        effort = self._current_effort()
        effort_str = str(effort) if effort is not None else "off"
        chain_info = ""
        try:
            chain = cfg.TRANSLATION_CHAIN
            steps = []
            for s in chain:
                t = s.get("type", "llm")
                if t == "llm":
                    p = s.get("provider", "?")
                    m = s.get("mode", "chat")
                    steps.append(f"{p}/{m}")
                else:
                    steps.append(t)
            chain_info = ", ".join(steps)
        except Exception:
            chain_info = "unknown"

        status_w = self.query_one("#status", StatusPanel)
        if status_w:
            status_w.update(
                "[bold #ff8800]>>> STATUS <<<[/bold #ff8800]\n"
                "──────────────────────────\n"
                f"[bold]Preset:[/bold]       [#44bbdd]{preset_name}[/#44bbdd]\n"
                f"[bold]Chain:[/bold]        [#44bbdd]{chain_info}[/#44bbdd]\n"
                f"[bold]Reasoning:[/bold]    [#ffaa33]{effort_str}[/#ffaa33]  [dim](F2)[/dim]\n"
                f"[bold]Port:[/bold]         [#ffaa33]5555[/#ffaa33]\n"
                f"[bold]Translations:[/bold] [#33aa33]{self.msg_count}[/#33aa33]\n"
                f"[bold]Errors:[/bold]       [#cc3333]{self.err_count}[/#cc3333]\n"
                f"[bold]Prompt tokens:[/bold] [#ffaa33]{self.prompt_tokens}[/#ffaa33]\n"
                f"[bold]Output tokens:[/bold] [#44bbdd]{self.completion_tokens}[/#44bbdd]\n"
                f"[bold]Uptime:[/bold]       {uptime}\n"
                "──────────────────────────"
            )

        stats = self.query_one("#stats-bar", Static)
        if stats:
            stats.update(f"{icon}  {self._status_msg}")

    def _periodic_update(self):
        self._update_status()

    def _write_raw(self, text: str):
        log = self.query_one("#log-widget", RichLog)
        if log:
            log.write(text)

    def action_copy_logs(self):
        full = "\n".join(self._all_logs)
        if not full:
            self._write_raw("[dim]Log is empty[/dim]")
            return
        try:
            proc = subprocess.Popen(["clip.exe"], stdin=subprocess.PIPE, text=True)
            proc.communicate(input=full, timeout=5)
            self._write_raw("[bold #44bbdd]>> Logs copied to clipboard[/bold #44bbdd]")
        except Exception as e:
            self._write_raw(f"[#cc3333]Copy failed: {e}[/#cc3333]")

    def action_select_preset(self):
        def callback(key: str | None):
            if key:
                self._current_preset_key = key
                p = cfg.PRESETS.get(key, {})
                self._current_preset_name = p.get("name", key)
                label = p.get("name", key)
                self._write_raw(f"[bold #ff8800]>> Selected: {label}[/bold #ff8800]")
                self._write_raw("[dim]  Press F3 to apply[/dim]")
                self._update_status()

        self.push_screen(PresetSelectScreen(), callback)

    def action_restart_server(self):
        self._write_raw("[bold #ffaa33]>> Restarting server...[/bold #ffaa33]")
        self.msg_count = 0
        self.err_count = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._all_logs.clear()
        self.start_time = datetime.now()
        server_proc.restart(self._current_preset_key)

    def _current_effort(self) -> str | None:
        t = server_proc.translator
        if t:
            return t.reasoning_effort.get(cfg.DEFAULT_PROVIDER)
        return None
    def _toggle_effort_direct(self, direction: str = "next"):
        try:
            t = server_proc.translator
            if t:
                effort = t.toggle_reasoning(cfg.DEFAULT_PROVIDER, direction)
                label = "off" if effort is None else effort
                self._status_msg = f"Reasoning: {label}"
                self._update_status()
                self._write_raw(
                    f"[bold #44bbdd]>> Reasoning: {label}[/bold #44bbdd]"
                )
            else:
                self._write_raw("[dim]Server not running yet[/dim]")
        except Exception as e:
            self._write_raw(f"[#cc3333]Failed: {e}[/#cc3333]")

    def action_toggle_reasoning(self):
        self._toggle_effort_direct("next")

    def action_clear_log(self):
        w = self.query_one("#log-widget", RichLog)
        if w:
            w.clear()
        self._all_logs.clear()

    def action_quit(self):
        server_proc.stop()
        self.exit()


def main():
    app = TranslatorTUI()
    app.run()


if __name__ == "__main__":
    main()
