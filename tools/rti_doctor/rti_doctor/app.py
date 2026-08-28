"""The Textual application shell."""

from textual.app import App
from textual.containers import Container

from . import discovery
from .views.system_overview import SystemOverviewScreen


class RTIDoctorApp(App):
  """Same shape as rti_spy's App: a placeholder compose, screens pushed on mount."""

  CSS_PATH = None
  # No app-level "b" binding: the participant list is the base screen, and an
  # app-level back would pop it and reveal the empty placeholder screen. Each
  # pushed screen defines its own Back instead.
  BINDINGS = [("q", "quit", "Quit")]

  def __init__(self, session, interval=2.0):
    super().__init__()
    self.session = session
    self.interval = interval
    self._overview_screen = None

  def compose(self):
    yield Container()

  async def on_mount(self):
    self._overview_screen = SystemOverviewScreen(self.session)
    await self.push_screen(self._overview_screen)
    self.set_interval(self.interval, self._refresh)

  def _refresh(self):
    """Poll participant discovery and expire type waits on a timer."""
    discovery.refresh_participants(self.session.participant, self.session.registry)
    self.session.registry.expire_type_waits()


def available_theme_names():
  """The theme names the installed Textual registers, for `--theme` validation.

  Textual exposes its registry only on an App instance, and building one costs
  nothing here because `__init__` never touches the session - so the CLI can
  reject an unknown name before it creates a DDS participant, the same way
  rti_spy does.
  """
  return sorted(RTIDoctorApp(None).available_themes)
