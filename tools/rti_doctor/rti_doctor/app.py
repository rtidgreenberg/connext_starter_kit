"""The Textual application shell."""

import asyncio

from textual.app import App
from textual.containers import Container

from . import discovery
from .views.browse import ParticipantListScreen


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
    self._participant_screen = None

  def compose(self):
    yield Container()

  async def on_mount(self):
    self._participant_screen = ParticipantListScreen(self.session)
    await self.push_screen(self._participant_screen)
    self.set_interval(self.interval, self._refresh)

  def _refresh(self):
    """Poll participant discovery and expire type waits on a timer."""
    discovery.refresh_participants(self.session.participant, self.session.registry)
    self.session.registry.expire_type_waits()
    screen = self._participant_screen
    if screen is not None and self.screen is screen:
      asyncio.create_task(screen.refresh_table())
