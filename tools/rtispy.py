import rti.connextdds as dds
import time
import argparse
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Header, Footer, Static
from textual.containers import Container
from textual.screen import Screen
from textual import events
import logging
from textual.logging import TextualHandler
import asyncio

logging.basicConfig(
    level="NOTSET",
    handlers=[TextualHandler()],
)

# Global maps
endpoints = {}
participants = {}


class Participant:
    def __init__(self, name=None, ip=None):
        self.name = name
        self.ip = ip


class Endpoint:
  def __init__(self, key=None, topic_name=None, type_name=None, type=None, kind=None, p_ip=None, p_name=None, p_key=None):
      self.key = key,
      self.topic_name = topic_name
      self.type_name = type_name
      self.type = type
      self.kind = kind
      self.p_ip = p_ip
      self.p_name = p_name
      self.p_key = p_key

class ParticipantListScreen(Screen):

  def __init__(self, app_ref, participant):
    super().__init__()
    self.app_ref = app_ref
    self.table = DataTable()
    self.selected_key = None
    self.participant = participant

  def compose(self) -> ComposeResult:
    logging.debug("[ParticipantsScreen.compose] called")
    yield Header()
    yield Static("")
    yield Static("Directions: Select a participant and hit Enter to view endpoints.", id="directions")
    yield Static("")
    yield Container(self.table)
    yield Footer()

  async def on_mount(self) -> None:
    await self.refresh_table()

  async def refresh_table(self):
    # logging.debug(f"[ParticipantsScreen.refresh_table] called, participants: {len(participants)}")
    prev_selected = self.selected_key
    self.table.clear()
    if not self.table.columns:
      self.table.add_columns("Participant Name", "IP")
  
    for idx, (p_key, participant) in enumerate(participants.items()):
      # logging.debug(f"[ParticipantsScreen.refresh_table] adding row: {participant.name}, {participant.ip}, key={p_key}")
      self.table.add_row(participant.name, participant.ip, key=p_key)


    self.table.cursor_type = "row"
    self.table.focus()
    # Restore selection by row index, not key
    if self.selected_key is not None:
      for idx, row in enumerate(self.table.rows):
        if row == self.selected_key:
          self.table.move_cursor(row=idx)
          break
    # logging.debug(f"[ParticipantsScreen.refresh_table] table row count: {len(self.table.rows)}")
    self.table.refresh()

  async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
    self.selected_key = event.row_key

  async def on_key(self, event: events.Key) -> None:
    if event.key == "enter" and self.selected_key is not None:
      await self.app_ref.push_screen(EndpointListScreen(self.app_ref, self.selected_key, self.participant))

class EndpointListScreen(Screen):
  def __init__(self, app_ref, participant_key, participant):
    super().__init__()
    self.app_ref = app_ref
    self.participant_key = participant_key
    self.table = DataTable()
    self.selected_key = None
    self.participant = participant

  def compose(self) -> ComposeResult:
    yield Header()
    yield Static("")
    yield Static("Directions: Select an endpoint and hit Enter for more detail/subscribe.", id="directions")
    yield Static("")
    yield Container(self.table)
    yield Footer()

  async def on_mount(self) -> None:
    self.table.clear()
    self.table.add_columns("Topic Name", "Kind")
    for key, entity in endpoints.items():
      if getattr(entity, 'p_key', None) == self.participant_key:
        self.table.add_row(entity.topic_name, entity.kind, key=key)
    self.table.cursor_type = "row"

  async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
    self.selected_key = event.row_key

  async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
    self.selected_key = event.row_key

  async def on_key(self, event: events.Key) -> None:
    if event.key == "enter" and self.selected_key is not None:

      endpoint = endpoints.get(self.selected_key)
      if endpoint:
        # logging.debug(f"[action_select] Opening TopicDetailScreen for endpoint: {endpoint.topic_name}")
        
        if self.participant:
          await self.app_ref.push_screen(ParticipantDetailScreen(endpoint, self.participant))



class ParticipantDetailScreen(Screen):
  def __init__(self, endpoint, participant):
    super().__init__()
    self.endpoint = endpoint
    self.participant = participant
    self.sample_lines = []
    self.table = DataTable()

  def compose(self) -> ComposeResult:
    yield Header()
    yield Container(self.table)
    # from textual.widgets import Static
    self.output_widget = Static("Waiting for samples...\n")
    yield self.output_widget
    yield Footer()

  async def on_mount(self) -> None:
    if getattr(self.endpoint, 'kind', None) == 'Writer':
        self._sub_task = asyncio.create_task(self.subscribe_topic())
    else:
        self.output_widget.update("Subscription only available for Writer endpoints.")

  async def subscribe_topic(self):
    try:
      if not self.endpoint.type:
        self.output_widget.update("Error: No type information available for this topic.")
        return
      if not isinstance(self.endpoint.type, dds.DynamicType):
        self.output_widget.update("Error: Discovered type is not a DynamicType. Cannot subscribe with DynamicData.")
        return
      
      # if not self.endpoint.topic_name:
      #   logging.debug("NO TOPIC")

      # if not self.participant:
      #   logging.debug("NO PARTICIPANT")

      
      # logging.debug(f"TOPIC NAME: {self.endpoint.topic_name}  TYPE: {self.endpoint.type}")
      
      dynamic_topic = dds.DynamicData.Topic(self.participant, self.endpoint.topic_name, self.endpoint.type)
      dynamic_reader = dds.DynamicData.DataReader(dynamic_topic)
      self.output_widget.update(f"Subscribed to topic '{self.endpoint.topic_name}' with discovered type.\nWaiting for samples...\n")

      while True:
        await asyncio.sleep(0.1)
        for data, info in dynamic_reader.take():
          if info.valid:
            # Access the writer's instance handle from the sample info
            writer_handle = info.publication_handle

            # Get the Participant Info for the matched DataWriter
            participant_data = dynamic_reader.matched_publication_participant_data(
                writer_handle)
            
            # Print out first locator
            ip_list = participant_data.default_unicast_locators[0].address[-4:]
            address_str = '.'.join(
                str(byte) for byte in ip_list)
            domain_id = participant_data.domain_id

            # Get first port
            port = participant_data.default_unicast_locators[0].port

            # Get Topic Name
            topic_name = dynamic_reader.topic_name

            line = f"[{address_str}:{port} D:{domain_id}] {topic_name}: {data}"
            self.sample_lines.append(line)

            self.sample_lines = self.sample_lines[-20:]
            self.output_widget.update("\n".join(self.sample_lines))
    except Exception as e:
      self.output_widget.update(f"Error: {e}")


# Listener for subscription discovery
class SubscriptionListener(dds.SubscriptionBuiltinTopicData.DataReaderListener):
  def on_data_available(self, reader):

    for data, info in reader.take():
      if info.valid:
        key_list = data.key.value
        key_string = str(key_list)

        type_name = data.type_name
        topic_name = data.topic_name

        p_key_list = data.participant_key.value
        p_key_string = str(p_key_list)

        reader = Endpoint(topic_name=topic_name,type_name=type_name, type=data.type, kind="Reader", p_key=p_key_string, key=key_string)

        if key_string not in endpoints:
          endpoints[key_string] = reader

# Listener for publication discovery
class PublicationListener(dds.PublicationBuiltinTopicData.DataReaderListener):

  def on_data_available(self, reader):

    for data, info in reader.take():
      if info.valid:
        key_list = data.key.value
        key_string = str(key_list)

        type_name = data.type_name
        topic_name = data.topic_name

        p_key_list = data.participant_key.value
        p_key_string = str(p_key_list)

        writer = Endpoint(topic_name=topic_name,type_name=type_name, type=data.type, kind="Writer", p_key=p_key_string, key=key_string)

        if key_string not in endpoints:
          endpoints[key_string] = writer


class RTISPY(App):
  CSS_PATH = None
  BINDINGS = [ ("q", "quit", "Quit"), ("b", "back", "Back") ]


  def __init__(self, participant, interval=2.0):
    super().__init__()
    self.participant = participant
    self.interval = interval
    self.table = None
    self.endpoints_table = []
    self.selected_key = None

  def compose(self) -> ComposeResult:
    # Yield a placeholder container; actual screens are pushed in on_mount
    yield Container()

  async def on_mount(self) -> None:
    # logging.debug("[on_mount] refreshing participants list")
    self.update_participants(self.participant)
    self.set_interval(self.interval, lambda: self.update_participants(self.participant))
    await self.push_screen(ParticipantListScreen(self, self.participant))


  def update_participants(self, participant):
    # logging.debug("[update_participants]")

    # Get current participants
    p_list = participant.discovered_participants()

    # logging.debug(f"[update_participants length] {len(p_list)}")

    for p in p_list:
        data = participant.discovered_participant_data(p)
        name = data.participant_name.name
        ip_list = data.default_unicast_locators[0].address[-4:]
        ip = '.'.join(str(byte) for byte in ip_list)

        participant_info = Participant(name, ip)

        key_list = data.key.value
        key_string = str(key_list)
        # logging.debug(f" Adding Participant {key_string}")

        participants[key_string] = participant_info

    # Refresh ParticipantsScreen if it's the current screen
    if self.screen_stack and isinstance(self.screen_stack[-1], ParticipantListScreen):
        coro = self.screen_stack[-1].refresh_table()
        if asyncio.iscoroutine(coro):
            asyncio.create_task(coro)

    async def action_back(self) -> None:
      # logging.warning("[action_back] before await pop_screen")
      await self.pop_screen()

def main():
  parser = argparse.ArgumentParser(description="Discover all readers and writers on a DDS domain.")
  parser.add_argument("-d", "--domain", type=int, default=1, help="DDS domain ID (default: 1)")
  parser.add_argument("-i", "--interval", type=float, default=10, help="Refresh interval in seconds (default: 2.0)")
  args = parser.parse_args()

  # Create participant in disabled state
  participant_factory_qos = dds.DomainParticipantFactoryQos()
  participant_factory_qos.entity_factory.autoenable_created_entities = False
  dds.DomainParticipant.participant_factory_qos = participant_factory_qos

  qos = dds.DomainParticipantQos()
  qos.participant_name.name = "RTI SPY"
  participant = dds.DomainParticipant(args.domain, qos=qos)

  # Set listeners for the built-in DataReaders
  participant.publication_reader.set_listener(PublicationListener(), dds.StatusMask.DATA_AVAILABLE)
  participant.subscription_reader.set_listener(SubscriptionListener(), dds.StatusMask.DATA_AVAILABLE)

  # Enable participant
  participant.enable()

  app = RTISPY(participant, interval=args.interval)
  app.run()

if __name__ == "__main__":
    main()