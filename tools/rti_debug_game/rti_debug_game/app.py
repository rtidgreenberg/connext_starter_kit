"""Interactive Textual front end for DDS Debug Game."""

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Static

from .generator import generate
from .levels import CATALOG
from .runtime import run_once


class DebugGameApp(App):
    """Level selection and Mission Contract view; Admin Console diagnoses DDS."""

    CSS = """
    Screen { background: #12251f; color: #eaf2e7; }
    #mission { height: auto; border: solid #77bd78; padding: 1 2; margin: 1 2; background: #19352c; }
    #status { height: 1fr; border: solid #d3a34b; padding: 1 2; margin: 1 2; color: #f8e1a5; }
    Horizontal { height: auto; margin: 0 2 1 2; }
    Button { margin-right: 1; }
    """
    BINDINGS = [("q", "quit", "Quit"), ("g", "generate", "Generate"),
                ("r", "run_level", "Run"), ("x", "reset_level", "Reset")]

    def __init__(self, level_id="L01"):
        super().__init__()
        self.level = CATALOG[level_id]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(self._mission_text(), id="mission")
        with Horizontal():
            yield Button("Generate scripts", id="generate", variant="primary")
            yield Button("Run round", id="run")
            yield Button("Reset level", id="reset", variant="warning")
        yield Static("Ready. Generate scripts, edit run/participant_*.py, then start a round.", id="status")
        yield Footer()

    def _mission_text(self):
        return (f"[b]{self.level.level_id}: {self.level.title}[/b]\n"
                f"Domain 42 | Topic {self.level.topic} | {', '.join(self.level.issue_categories)}\n"
                f"Mission Contract: {self.level.expected_reader} receives sequences 1-{self.level.samples_per_round} "
                f"from {self.level.expected_writer}.\n"
                "Inspect discovery and QoS in RTI Admin Console on domain 42.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "generate":
            self.action_generate()
        elif event.button.id == "run":
            self.action_run_level()
        elif event.button.id == "reset":
            self.action_reset_level()

    def action_generate(self):
        root = generate(self.level)
        self.query_one("#status", Static).update(f"Generated editable scripts in {root}.")

    def action_reset_level(self):
        root = generate(self.level, reset=True)
        self.query_one("#status", Static).update(f"Restored initial L01 fault in {root}.")

    def action_run_level(self):
        self.query_one("#status", Static).update("Running one verification round on domain 42...")
        self.run_worker(self._run_level, thread=True, exclusive=True)

    def _run_level(self):
        root = generate(self.level)
        result = run_once(self.level, root)
        received = sum(len(samples) for samples in result["received"].values())
        verdict = "PASS" if result["passed"] else "NOT YET"
        self.call_from_thread(
            self.query_one("#status", Static).update,
            f"{verdict}: observed {received} valid samples. Edit run/participant_*.py and run again.",
        )
