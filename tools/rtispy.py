import rti.connextdds as dds
import time
import argparse
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Header, Footer, Static
from textual.containers import Container, VerticalScroll
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
    def __init__(self, name=None, ip=None, rtps_host_id=None, rtps_app_id=None):
        self.name = name
        self.ip = ip
        self.rtps_host_id = rtps_host_id
        self.rtps_app_id = rtps_app_id


class Endpoint:
  def __init__(self, key=None, topic_name=None, type_name=None, type=None, kind=None, p_ip=None, p_name=None, p_key=None, 
               reliability=None, durability=None, deadline=None, ownership=None, presentation=None, partition=None):
      self.key = key,
      self.topic_name = topic_name
      self.type_name = type_name
      self.type = type
      self.kind = kind
      self.p_ip = p_ip
      self.p_name = p_name
      self.p_key = p_key
      self.reliability = reliability
      self.durability = durability
      self.deadline = deadline
      self.ownership = ownership
      self.presentation = presentation
      self.partition = partition

class ParticipantListScreen(Screen):

  CSS = """
  #participant_container {
      height: 30%;
      border: solid $accent;
  }
  
  #logger_container {
      height: 30%;
      border: solid $primary;
  }
  
  #admin_container {
      height: 10%;
      border: solid $secondary;
  }
  
  #error_container {
      height: 10%;
      border: solid $error;
  }
  """

  def __init__(self, app_ref, participant):
    super().__init__()
    self.app_ref = app_ref
    self.table = DataTable()
    self.selected_key = None
    self.participant = participant
    self.logger_output = None
    self.admin_output = None
    self.error_output = None
    self.distlog_reader = None
    self.distlog_subscriber = None
    self.distlog_topic = None
    self.logger_messages = []
    self.error_messages = []
    self.current_monitoring_key = None

  def compose(self) -> ComposeResult:
    logging.debug("[ParticipantsScreen.compose] called")
    yield Header()
    yield Static("")
    yield Static("Directions: Select a participant and hit Enter to view endpoints.", id="directions")
    yield Static("")
    with VerticalScroll(id="participant_container"):
      yield self.table
    yield Static("")
    yield Static("=== Distributed Logger Messages ===", id="logger_header")
    with VerticalScroll(id="logger_container"):
      self.logger_output = Static("No participant selected. Select a participant to view distributed logger messages.")
      yield self.logger_output
    yield Static("")
    yield Static("=== Remote Admin Commands ===", id="admin_header")
    yield Static("Press 'v' to change log verbosity for selected participant", id="admin_directions")
    with VerticalScroll(id="admin_container"):
      self.admin_output = Static("")
      yield self.admin_output
    yield Static("")
    yield Static("=== Error Log ===", id="error_header")
    with VerticalScroll(id="error_container"):
      self.error_output = Static("No errors logged.")
      yield self.error_output
    yield Footer()

  async def on_mount(self) -> None:
    await self.refresh_table()

  async def on_unmount(self) -> None:
    # Clean up distributed logger reader
    await self.cleanup_distlog_reader()

  def log_error(self, error_msg):
    """Log an error message to the error panel"""
    import datetime
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    error_line = f"[{timestamp}] {error_msg}"
    self.error_messages.append(error_line)
    
    # Keep only last 10 error messages
    if len(self.error_messages) > 10:
      self.error_messages.pop(0)
    
    # Update display
    if self.error_output:
      display_text = "\n".join(self.error_messages[-10:])
      self.error_output.update(display_text)

  async def cleanup_distlog_reader(self):
    if self.distlog_reader is not None:
      try:
        logging.info("[cleanup_distlog_reader] Closing distributed logger DataReader")
        self.distlog_reader.close()
        self.distlog_reader = None
      except Exception as e:
        error_msg = f"Error closing DataReader: {e}"
        logging.error(f"[cleanup_distlog_reader] {error_msg}")
        self.log_error(error_msg)
    
    if self.distlog_subscriber is not None:
      try:
        logging.info("[cleanup_distlog_reader] Closing distributed logger Subscriber")
        self.distlog_subscriber.close()
        self.distlog_subscriber = None
      except Exception as e:
        error_msg = f"Error closing Subscriber: {e}"
        logging.error(f"[cleanup_distlog_reader] {error_msg}")
        self.log_error(error_msg)
    
    # Don't delete the topic - it can be reused
    # Just clear the reference
    self.distlog_topic = None

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
    # Update logger output when participant is selected
    if self.selected_key and self.logger_output:
      participant = participants.get(self.selected_key)
      if participant:
        # Only clean up and start new monitoring if we're switching to a DIFFERENT participant
        if self.current_monitoring_key != self.selected_key:
          await self.cleanup_distlog_reader()
          self.logger_messages = []
          self.current_monitoring_key = self.selected_key
          self.logger_output.update(f"Monitoring distributed logger for: {participant.name}\nSearching for rti/distlog topic...")
          # Start monitoring in background
          asyncio.create_task(self.monitor_distlog())
        # If same participant, don't resubscribe - just continue monitoring

  async def on_key(self, event: events.Key) -> None:
    if event.key == "enter" and self.selected_key is not None:
      await self.app_ref.push_screen(EndpointListScreen(self.app_ref, self.selected_key, self.participant))
    elif event.key == "v" and self.selected_key is not None:
      # Handle verbosity change command
      participant = participants.get(self.selected_key)
      if participant and self.admin_output:
        self.admin_output.update(f"Changing log verbosity for {participant.name}...\n(Command functionality to be implemented)")

  async def monitor_distlog(self):
    """Monitor the rti/distlog topic for the currently selected participant"""
    try:
      # Look for the rti/distlog topic in endpoints for this participant
      distlog_endpoint = None
      for endpoint_key, endpoint in endpoints.items():
        if endpoint.p_key == self.selected_key and endpoint.topic_name == "rti/distlog":
          distlog_endpoint = endpoint
          break
      
      if not distlog_endpoint:
        self.logger_output.update(f"rti/distlog topic not found for this participant.\nThe participant may not have distributed logging enabled.")
        return
      
      if not distlog_endpoint.type:
        self.logger_output.update("Error: No type information available for rti/distlog topic.")
        return
      
      if not isinstance(distlog_endpoint.type, dds.DynamicType):
        self.logger_output.update("Error: Discovered type is not a DynamicType.")
        return
      
      # Find or create topic - reuse if it already exists
      try:
        self.distlog_topic = self.participant.find_topic("rti/distlog")
        logging.info("[monitor_distlog] Reusing existing rti/distlog topic")
      except:
        # Topic doesn't exist, create it
        self.distlog_topic = dds.DynamicData.Topic(self.participant, "rti/distlog", distlog_endpoint.type)
        logging.info("[monitor_distlog] Created new rti/distlog topic")
      
      # Get the selected participant's RTPS IDs for content filtering
      selected_participant = participants.get(self.selected_key)
      if not selected_participant:
        self.logger_output.update("Error: Could not find selected participant information.")
        return
      
      debug_msg = f"Selected participant: name={selected_participant.name}, rtps_host_id={selected_participant.rtps_host_id}, rtps_app_id={selected_participant.rtps_app_id}"
      logging.info(f"[monitor_distlog] {debug_msg}")
      self.log_error(debug_msg)
      
      # Create content filtered topic to only receive logs from the selected participant
      # Filter expression: match logs where hostAndAppId.rtps_host_id and hostAndAppId.rtps_app_id match
      filter_expression = "hostAndAppId.rtps_host_id = %0 AND hostAndAppId.rtps_app_id = %1"
      filter_parameters = [str(selected_participant.rtps_host_id), str(selected_participant.rtps_app_id)]
      
      debug_msg2 = f"Creating CFT with filter: {filter_expression}, parameters: {filter_parameters}"
      logging.info(f"[monitor_distlog] {debug_msg2}")
      self.log_error(debug_msg2)
      
      # Create content filtered topic
      try:
        filtered_topic_name = f"rti/distlog_filtered_{selected_participant.rtps_host_id}_{selected_participant.rtps_app_id}"
        # ContentFilteredTopic constructor: (topic, name, Filter(expression, parameters))
        # Use DynamicData.ContentFilteredTopic since distlog_topic is a DynamicData.Topic
        content_filtered_topic = dds.DynamicData.ContentFilteredTopic(
            self.distlog_topic,
            filtered_topic_name,
            dds.Filter(filter_expression, filter_parameters)
        )
        logging.info(f"[monitor_distlog] Created content filtered topic with hostAndAppId.rtps_host_id={selected_participant.rtps_host_id}, hostAndAppId.rtps_app_id={selected_participant.rtps_app_id}")
      except Exception as e:
        error_msg = f"Failed to create content filtered topic: {e}"
        logging.error(f"[monitor_distlog] {error_msg}")
        self.logger_output.update(error_msg)
        self.log_error(error_msg)
        return
      
      # Create subscriber with partition and presentation QoS if available
      subscriber_qos = dds.SubscriberQos()
      qos_set = False
      
      if distlog_endpoint.partition:
        subscriber_qos.partition.name = distlog_endpoint.partition.name
        qos_set = True
        logging.info(f"[monitor_distlog] Setting subscriber partitions: {', '.join(distlog_endpoint.partition.name)}")
      
      if distlog_endpoint.presentation:
        subscriber_qos.presentation.access_scope = distlog_endpoint.presentation.access_scope
        subscriber_qos.presentation.coherent_access = distlog_endpoint.presentation.coherent_access
        subscriber_qos.presentation.ordered_access = distlog_endpoint.presentation.ordered_access
        qos_set = True
        logging.info(f"[monitor_distlog] Setting subscriber presentation: access_scope={distlog_endpoint.presentation.access_scope}")
      
      if qos_set:
        self.distlog_subscriber = dds.Subscriber(self.participant, subscriber_qos)
      else:
        self.distlog_subscriber = dds.Subscriber(self.participant)
      
      # Create DataReader QoS and apply discovered writer's QoS settings
      reader_qos = dds.DataReaderQos()
      
      if distlog_endpoint.reliability:
        reader_qos.reliability.kind = distlog_endpoint.reliability.kind
        reader_qos.reliability.max_blocking_time = distlog_endpoint.reliability.max_blocking_time
        logging.info(f"[monitor_distlog] Setting reliability: {distlog_endpoint.reliability.kind}")
      
      if distlog_endpoint.durability:
        reader_qos.durability.kind = distlog_endpoint.durability.kind
        logging.info(f"[monitor_distlog] Setting durability: {distlog_endpoint.durability.kind}")
      
      if distlog_endpoint.deadline:
        reader_qos.deadline.period = distlog_endpoint.deadline.period
        logging.info(f"[monitor_distlog] Setting deadline: {distlog_endpoint.deadline.period}")
      
      if distlog_endpoint.ownership:
        reader_qos.ownership.kind = distlog_endpoint.ownership.kind
        logging.info(f"[monitor_distlog] Setting ownership: {distlog_endpoint.ownership.kind}")
      
      # Create DataReader with matched QoS using the content filtered topic
      self.distlog_reader = dds.DynamicData.DataReader(self.distlog_subscriber, content_filtered_topic, reader_qos)
      
      self.logger_output.update(f"Subscribed to rti/distlog topic with content filter (host_id={selected_participant.rtps_host_id}, app_id={selected_participant.rtps_app_id}).\nWaiting for log messages...\n")
      logging.info(f"[monitor_distlog] Successfully subscribed to rti/distlog with content filter")
      
      # Start reading samples
      asyncio.create_task(self.read_distlog_samples())
      
    except Exception as e:
      error_msg = f"Error subscribing to rti/distlog: {e}"
      logging.error(f"[monitor_distlog] {error_msg}")
      self.logger_output.update(error_msg)
      self.log_error(error_msg)

  async def read_distlog_samples(self):
    """Continuously read samples from the distributed logger"""
    try:
      while self.distlog_reader is not None:
        samples = self.distlog_reader.take()
        for sample in samples:
          if sample.info.valid:
            try:
              # Get member names using the fields method
              member_names = list(sample.data.fields())
              
              # Create log line with all fields except hostAndAppId
              log_line = " | ".join([f"{name}: {sample.data[name]}" for name in member_names if name != 'hostAndAppId'])
              self.logger_messages.append(log_line)
              
              # Keep only last 20 messages
              if len(self.logger_messages) > 20:
                self.logger_messages.pop(0)
              
              # Update display
              display_text = f"Monitoring rti/distlog topic:\n" + "\n".join(self.logger_messages[-20:])
              self.logger_output.update(display_text)
              
            except Exception as e:
              error_msg = f"Error processing distlog sample: {e}"
              logging.error(f"[read_distlog_samples] {error_msg}")
              self.log_error(error_msg)
        
        await asyncio.sleep(0.1)  # Small delay between reads
        
    except Exception as e:
      error_msg = f"Error reading distlog samples: {e}"
      logging.error(f"[read_distlog_samples] {error_msg}")
      self.log_error(error_msg)

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
    self.dynamic_reader = None
    self.subscriber = None

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

  async def on_unmount(self) -> None:
    # Clean up reader and subscriber when screen is unmounted
    if self.dynamic_reader is not None:
      try:
        logging.info(f"[on_unmount] Closing DataReader for topic: {self.endpoint.topic_name}")
        self.dynamic_reader.close()
        self.dynamic_reader = None
      except Exception as e:
        logging.error(f"[on_unmount] Error closing DataReader: {e}")
    
    if self.subscriber is not None:
      try:
        logging.info(f"[on_unmount] Closing Subscriber")
        self.subscriber.close()
        self.subscriber = None
      except Exception as e:
        logging.error(f"[on_unmount] Error closing Subscriber: {e}")

  async def subscribe_topic(self):
    try:
      if not self.endpoint.type:
        self.output_widget.update("Error: No type information available for this topic.")
        return
      if not isinstance(self.endpoint.type, dds.DynamicType):
        self.output_widget.update("Error: Discovered type is not a DynamicType. Cannot subscribe with DynamicData.")
        return
      
      # Create topic
      dynamic_topic = dds.DynamicData.Topic(self.participant, self.endpoint.topic_name, self.endpoint.type)
      
      # Create subscriber with partition and presentation QoS if available
      subscriber_qos = dds.SubscriberQos()
      qos_set = False
      
      if self.endpoint.partition:
        subscriber_qos.partition.name = self.endpoint.partition.name
        qos_set = True
        logging.info(f"[subscribe_topic] Setting subscriber partitions: {', '.join(self.endpoint.partition.name)}")
      
      if self.endpoint.presentation:
        subscriber_qos.presentation.access_scope = self.endpoint.presentation.access_scope
        subscriber_qos.presentation.coherent_access = self.endpoint.presentation.coherent_access
        subscriber_qos.presentation.ordered_access = self.endpoint.presentation.ordered_access
        qos_set = True
        logging.info(f"[subscribe_topic] Setting subscriber presentation: access_scope={self.endpoint.presentation.access_scope}")
      
      if qos_set:
        subscriber = dds.Subscriber(self.participant, subscriber_qos)
      else:
        subscriber = dds.Subscriber(self.participant)
      
      # Store subscriber reference for cleanup
      self.subscriber = subscriber
      
      # Create DataReader QoS and apply discovered writer's QoS settings
      reader_qos = dds.DataReaderQos()
      
      if self.endpoint.reliability:
        # Apply reliability QoS from writer
        reader_qos.reliability.kind = self.endpoint.reliability.kind
        reader_qos.reliability.max_blocking_time = self.endpoint.reliability.max_blocking_time
        
        # Apply durability QoS if available
        if self.endpoint.durability:
          reader_qos.durability.kind = self.endpoint.durability.kind
        
        # Apply deadline QoS if available
        if self.endpoint.deadline:
          reader_qos.deadline.period = self.endpoint.deadline.period
        
        # Apply ownership QoS if available
        if self.endpoint.ownership:
          reader_qos.ownership.kind = self.endpoint.ownership.kind
        
        logging.info(f"[subscribe_topic] Applying QoS - Reliability: {self.endpoint.reliability.kind}, Durability: {self.endpoint.durability.kind if self.endpoint.durability else 'N/A'}, Ownership: {self.endpoint.ownership.kind if self.endpoint.ownership else 'N/A'}")
        
        dynamic_reader = dds.DynamicData.DataReader(subscriber, dynamic_topic, reader_qos)
        # Store reader reference for cleanup
        self.dynamic_reader = dynamic_reader
        
        qos_info = f"Reliability: {self.endpoint.reliability.kind}\n"
        qos_info += f"Durability: {self.endpoint.durability.kind if self.endpoint.durability else 'N/A'}\n"
        qos_info += f"Ownership: {self.endpoint.ownership.kind if self.endpoint.ownership else 'N/A'}\n"
        if self.endpoint.partition and len(self.endpoint.partition.name) > 0:
          qos_info += f"Partitions: {', '.join(self.endpoint.partition.name)}\n"
        self.output_widget.update(f"Subscribed to topic '{self.endpoint.topic_name}' with matched QoS.\n{qos_info}Waiting for samples...\n")
      else:
        # Fallback to default QoS if no QoS captured
        dynamic_reader = dds.DynamicData.DataReader(subscriber, dynamic_topic)
        # Store reader reference for cleanup
        self.dynamic_reader = dynamic_reader
        self.output_widget.update(f"Subscribed to topic '{self.endpoint.topic_name}' with default QoS.\nWaiting for samples...\n")

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

        # Extract individual QoS policies from builtin topic data
        reliability = data.reliability
        durability = data.durability
        deadline = data.deadline
        ownership = data.ownership
        presentation = data.presentation
        partition = data.partition

        logging.info(f"[SubscriptionListener] Discovered Reader: topic='{topic_name}', type='{type_name}', key={key_string}")
        logging.info(f"[SubscriptionListener] Reader QoS - Reliability: {reliability.kind}, Durability: {durability.kind}, Ownership: {ownership.kind}")

        reader = Endpoint(topic_name=topic_name, type_name=type_name, type=data.type, kind="Reader", 
                         p_key=p_key_string, key=key_string, reliability=reliability, 
                         durability=durability, deadline=deadline, ownership=ownership,
                         presentation=presentation, partition=partition)

        if key_string not in endpoints:
          endpoints[key_string] = reader
          logging.info(f"[SubscriptionListener] Added new Reader endpoint: {topic_name}")
        else:
          logging.debug(f"[SubscriptionListener] Reader endpoint already exists: {topic_name}")

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

        # Extract individual QoS policies from builtin topic data
        reliability = data.reliability
        durability = data.durability
        deadline = data.deadline
        ownership = data.ownership
        presentation = data.presentation
        partition = data.partition

        logging.info(f"[PublicationListener] Discovered Writer: topic='{topic_name}', type='{type_name}', key={key_string}")
        logging.info(f"[PublicationListener] Writer QoS - Reliability: {reliability.kind}, Durability: {durability.kind}, Ownership: {ownership.kind}")

        writer = Endpoint(topic_name=topic_name, type_name=type_name, type=data.type, kind="Writer", 
                         p_key=p_key_string, key=key_string, reliability=reliability, 
                         durability=durability, deadline=deadline, ownership=ownership,
                         presentation=presentation, partition=partition)

        if key_string not in endpoints:
          endpoints[key_string] = writer
          logging.info(f"[PublicationListener] Added new Writer endpoint: {topic_name}")
        else:
          logging.debug(f"[PublicationListener] Writer endpoint already exists: {topic_name}")


class RTISPY(App):
  CSS_PATH = None
  BINDINGS = [ ("q", "quit", "Quit"), ("b", "back", "Back"), ("v", "change_verbosity", "Change Verbosity") ]


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
        
        # Extract RTPS host ID and app ID from the participant key
        key_value = data.key.value  # Returns a tuple/list of 4 integers (not bytes)
        
        # The key.value contains 4 integers - we need to determine which ones contain host_id and app_id
        # RTPS uses the first 12 bytes (3 integers) as the GuidPrefix
        # Try using the first two integers as host_id and app_id
        if len(key_value) >= 2:
            rtps_host_id = key_value[0]
            rtps_app_id = key_value[1]
        else:
            rtps_host_id = 0
            rtps_app_id = 0

        participant_info = Participant(name, ip, rtps_host_id, rtps_app_id)

        key_string = str(key_value)
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
  
  async def action_quit(self) -> None:
    # Clean up any ParticipantDetailScreen instances before quitting
    for screen in self.screen_stack:
      if isinstance(screen, ParticipantDetailScreen):
        if screen.dynamic_reader is not None:
          try:
            logging.info(f"[action_quit] Closing DataReader for topic: {screen.endpoint.topic_name}")
            screen.dynamic_reader.close()
            screen.dynamic_reader = None
          except Exception as e:
            logging.error(f"[action_quit] Error closing DataReader: {e}")
        
        if screen.subscriber is not None:
          try:
            logging.info(f"[action_quit] Closing Subscriber")
            screen.subscriber.close()
            screen.subscriber = None
          except Exception as e:
            logging.error(f"[action_quit] Error closing Subscriber: {e}")
    
    # Now exit the application
    self.exit()

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