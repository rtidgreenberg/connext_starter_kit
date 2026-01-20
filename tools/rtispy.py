import rti.connextdds as dds
import time
import argparse
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Header, Footer, Static, Select, Button, RichLog
from textual.containers import Container, VerticalScroll, Vertical
from textual.screen import Screen, ModalScreen
from textual import events
import logging
from textual.logging import TextualHandler
import asyncio
import rti.asyncio

logging.basicConfig(
    level="NOTSET",
    handlers=[TextualHandler()],
)

# Global maps
endpoints = {}
participants = {}


class Participant:
    """Represents a DDS participant discovered in the domain.
    
    DDS: Each application creates a DomainParticipant which serves as the entry point
    to DDS. The RTPS host_id and app_id uniquely identify participants system-wide.
    """
    def __init__(self, name=None, ip=None, rtps_host_id=None, rtps_app_id=None):
        self.name = name
        self.ip = ip
        self.rtps_host_id = rtps_host_id
        self.rtps_app_id = rtps_app_id


class Endpoint:
  """Represents a DDS DataReader or DataWriter discovered via builtin topics.
  
  DDS: Builtin topics provide discovery information about remote endpoints (readers/writers).
  This includes the topic they communicate on, their QoS policies, and which participant owns them.
  QoS policies control reliability, durability, ordering, and other communication behaviors.
  """
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
  #welcome_panel {
      height: 30%;
      border: solid $primary;
      padding: 1 2;
      margin-bottom: 1;
  }
  
  #participant_container {
      height: 70%;
      border: solid $accent;
  }
  """

  def __init__(self, app_ref, participant):
    super().__init__()
    self.app_ref = app_ref
    self.table = DataTable()
    self.selected_key = None
    self.participant = participant

  def compose(self) -> ComposeResult:
    logging.debug("[ParticipantsScreen.compose] called")
    yield Header()
    with Container(id="welcome_panel"):
      yield Static("[bold cyan]Welcome to RTI Python Spy[/bold cyan]\n")
      yield Static("This tool monitors DDS participants and their endpoints.\n")
      yield Static("[yellow]Instructions:[/yellow]")
      yield Static("  • Select a participant from the table below")
      yield Static("  • Press [bold green]Enter[/bold green] to view DataReaders and DataWriters")
      yield Static("  • Press [bold green]L[/bold green] to open the Distributed Logger dialog")
      yield Static("  • Press [bold green]Q[/bold green] to quit")
    with VerticalScroll(id="participant_container"):
      yield self.table
    yield Footer()

  async def on_mount(self) -> None:
    await self.refresh_table()

  async def refresh_table(self):
    self.table.clear()
    if not self.table.columns:
      self.table.add_columns("Participant Name", "IP")
  
    for idx, (p_key, participant) in enumerate(participants.items()):
      self.table.add_row(participant.name, participant.ip, key=p_key)

    self.table.cursor_type = "row"
    self.table.focus()
    # Restore selection
    if self.selected_key is not None:
      for idx, row in enumerate(self.table.rows):
        if row == self.selected_key:
          self.table.move_cursor(row=idx)
          break
    self.table.refresh()

  async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
    self.selected_key = event.row_key

  async def on_key(self, event: events.Key) -> None:
    if event.key == "enter" and self.selected_key is not None:
      await self.app_ref.push_screen(EndpointListScreen(self.app_ref, self.selected_key, self.participant))
    elif event.key == "l" and self.selected_key is not None:
      participant = participants.get(self.selected_key)
      if participant:
        await self.app_ref.push_screen(DistributedLoggerDialog(self.participant, participant, self.selected_key))

class DistributedLoggerDialog(ModalScreen):
  """Modal dialog for viewing distributed logger messages, state, and changing filter level"""
  
  BINDINGS = [("b", "dismiss", "Back"), ("escape", "dismiss", "Close")]
  
  CSS = """
  DistributedLoggerDialog {
      align: center middle;
  }
  
  #dialog {
      width: 90%;
      height: 90%;
      border: thick $background 80%;
      background: $surface;
      padding: 1 2;
  }
  
  #dialog_title {
      text-align: center;
      text-style: bold;
      margin-bottom: 1;
  }
  
  #logger_messages {
      height: 40%;
      border: solid $primary;
  }
  
  #logger_state {
      height: 10%;
      border: solid $secondary;
      margin-top: 1;
      overflow-y: auto;
  }
  
  #filter_level_container {
      height: auto;
      margin-top: 1;
      margin-bottom: 1;
  }
  
  #filter_level_label {
      margin-bottom: 1;
  }
  
  #select_filter_level {
      width: 40;
      border: solid $accent;
      background: $surface;
  }
  
  #debug_container {
      height: 20%;
      border: solid $warning;
      margin-top: 1;
      overflow-y: auto;
  }
  
  .section_label {
      margin-top: 1;
      text-style: bold;
  }
  """
  
  FILTER_LEVEL_OPTIONS = [
      ("SILENT (0)", 0),
      ("FATAL (100)", 100),
      ("SEVERE (200)", 200),
      ("ERROR (300)", 300),
      ("WARNING (400)", 400),
      ("NOTICE (500)", 500),
      ("INFO (600)", 600),
      ("DEBUG (700)", 700),
      ("TRACE (800)", 800),
  ]
  
  def __init__(self, local_participant, target_participant, participant_key):
    super().__init__()
    self.local_participant = local_participant
    self.target_participant = target_participant
    self.participant_key = participant_key
    self.distlog_reader = None
    self.state_reader = None
    self.distlog_subscriber = None
    self.state_subscriber = None
    self.logger_output = None
    self.state_output = None
    self.debug_output = None
    self.filter_level_select = None
    self.current_filter_level = 600
    self.distlog_read_task = None
    self.distlog_topic = None
    self.state_topic = None
    self.debug_messages = []
    self.initialized = False
  
  def compose(self) -> ComposeResult:
    with Vertical(id="dialog"):
      yield Static(f"Distributed Logger - {self.target_participant.name}", id="dialog_title")
      
      yield Static("Log Messages:", classes="section_label")
      with VerticalScroll(id="logger_messages"):
        self.logger_output = RichLog(highlight=True, markup=True)
        yield self.logger_output
      
      yield Static("State:", classes="section_label")
      with VerticalScroll(id="logger_state"):
        self.state_output = Static("Waiting for state...")
        yield self.state_output
      
      yield Static("Change Filter Level:", id="filter_level_label", classes="section_label")
      with Container(id="filter_level_container"):
        self.filter_level_select = Select(
            options=self.FILTER_LEVEL_OPTIONS,
            value=self.current_filter_level,
            id="select_filter_level"
        )
        yield self.filter_level_select
      
      yield Static("Debug:", classes="section_label")
      with VerticalScroll(id="debug_container"):
        self.debug_output = Static("No debug messages.")
        yield self.debug_output
      
      with Container():
        yield Button("Close", variant="primary", id="close")
    yield Footer()
  
  async def on_mount(self) -> None:
    asyncio.create_task(self.monitor_distlog())
    asyncio.create_task(self.monitor_state())
    # Set initialized flag after tasks are started
    self.initialized = True
  
  async def on_unmount(self) -> None:
    if self.distlog_read_task:
      self.distlog_read_task.cancel()
      try:
        await self.distlog_read_task
      except asyncio.CancelledError:
        pass
    if self.distlog_reader:
      self.distlog_reader.close()
    if self.state_reader:
      self.state_reader.close()
    if self.distlog_subscriber:
      self.distlog_subscriber.close()
    if self.state_subscriber:
      self.state_subscriber.close()
  
  def on_button_pressed(self, event: Button.Pressed) -> None:
    if event.button.id == "close":
      self.dismiss()
  
  def log_debug(self, debug_msg):
    """Log a debug message to the debug panel"""
    import datetime
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    debug_line = f"[{timestamp}] {debug_msg}"
    self.debug_messages.append(debug_line)
    
    # Keep only last 10 debug messages
    if len(self.debug_messages) > 10:
      self.debug_messages.pop(0)
    
    # Update display in reverse order (most recent first)
    if self.debug_output:
      display_text = "\n".join(reversed(self.debug_messages[-10:]))
      self.debug_output.update(display_text)
  
  def on_select_changed(self, event: Select.Changed) -> None:
    if event.select.id == "select_filter_level" and self.initialized:
      new_level = event.value
      # Only send if value actually changed from current level
      if new_level != self.current_filter_level:
        # Ensure we have valid host/app IDs before sending command
        if self.target_participant.rtps_host_id == 0 and self.target_participant.rtps_app_id == 0:
          self.log_debug("Cannot send command: host/app ID not yet available. Please wait for state to load.")
        else:
          asyncio.create_task(self.send_filter_level_command(new_level))
  
  async def monitor_distlog(self):
    """Monitor distributed logger messages"""
    try:
      # DDS: Find the endpoint discovered via builtin topics
      # This gives us the writer's QoS so we can match it with our reader
      distlog_endpoint = None
      for endpoint_key, endpoint in endpoints.items():
        if endpoint.p_key == self.participant_key and endpoint.topic_name == "rti/distlog":
          distlog_endpoint = endpoint
          break
      
      if not distlog_endpoint or not distlog_endpoint.type:
        error_msg = "rti/distlog topic not found or no type information available."
        self.log_debug(error_msg)
        return
      
      if self.distlog_topic is None:
        try:
          # DDS: Try to find existing topic first (best practice)
          self.distlog_topic = self.local_participant.find_topic("rti/distlog")
          self.log_debug("Found existing distlog topic")
        except Exception as e:
          try:
            # DDS: Create topic using DynamicData with type discovered from builtin topics
            # This allows subscribing to topics without compile-time generated code
            self.distlog_topic = dds.DynamicData.Topic(self.local_participant, "rti/distlog", distlog_endpoint.type)
            self.log_debug("Created new distlog topic")
          except Exception as topic_error:
            error_msg = f"Failed to create distlog topic: {topic_error}"
            self.log_debug(error_msg)
            logging.error(f"[monitor_distlog] {error_msg}")
            return
      
      # DDS: Create ContentFilteredTopic to receive only messages from target participant
      # Filtering happens at the source, reducing network traffic and CPU overhead
      # Filter expression uses SQL-like syntax with numbered parameters (%0, %1)
      filter_expression = "hostAndAppId.rtps_host_id = %0 AND hostAndAppId.rtps_app_id = %1"
      filter_parameters = [str(self.target_participant.rtps_host_id), str(self.target_participant.rtps_app_id)]
      
      filtered_topic_name = f"rti/distlog_filtered_{self.target_participant.rtps_host_id}_{self.target_participant.rtps_app_id}"
      content_filtered_topic = dds.DynamicData.ContentFilteredTopic(
          self.distlog_topic,
          filtered_topic_name,
          dds.Filter(filter_expression, filter_parameters)
      )
      
      # DDS: Match subscriber partition QoS with discovered writer's partition
      # Readers and writers must be in matching partitions to communicate
      subscriber_qos = dds.SubscriberQos()
      if distlog_endpoint.partition:
        subscriber_qos.partition.name = distlog_endpoint.partition.name
      
      self.distlog_subscriber = dds.Subscriber(self.local_participant, subscriber_qos if distlog_endpoint.partition else None)
      
      # DDS: Configure reader QoS to match or be compatible with writer's QoS
      # The reader drives QoS matching - as long as reader requests "lower" QoS than writer provides, they match
      # Reliability: Reader can request BEST_EFFORT even if writer offers RELIABLE (but not vice versa)
      # Durability: Reader must request <= writer's durability to match (VOLATILE <= TRANSIENT_LOCAL <= PERSISTENT)
      #             For distlog, we match the writer's durability to receive late-joiner historical samples
      # Note: Full QoS matching shown here for reference - not all policies may be strictly necessary for this scenario
      reader_qos = dds.DataReaderQos()
      if distlog_endpoint.reliability:
        reader_qos.reliability.kind = distlog_endpoint.reliability.kind
      if distlog_endpoint.durability:
        reader_qos.durability.kind = distlog_endpoint.durability.kind
      
      self.distlog_reader = dds.DynamicData.DataReader(self.distlog_subscriber, content_filtered_topic, reader_qos)
      self.logger_output.write("Monitoring distributed logger messages...")
      
      self.distlog_read_task = asyncio.create_task(self.read_distlog_samples())
      
    except Exception as e:
      error_msg = f"Error subscribing to distributed logger: {e}"
      self.log_debug(error_msg)
      logging.error(f"[monitor_distlog] {e}")
  
  async def read_distlog_samples(self):
    """Read distributed logger samples"""
    try:
      while self.distlog_reader is not None:
        # DDS: take() removes samples from reader cache (vs read() which leaves them)
        # Returns list of SampleInfo + data tuples
        samples = self.distlog_reader.take()
        for sample in samples:
          # DDS: Check if sample is valid data (not metadata like dispose/unregister)
          if sample.info.valid:
            try:
              member_names = list(sample.data.fields())
              log_line = " | ".join([f"{name}: {sample.data[name]}" for name in member_names if name != 'hostAndAppId'])
              self.logger_output.write(log_line)
            except Exception as e:
              error_msg = f"Error processing sample: {e}"
              logging.error(f"[read_distlog_samples] {error_msg}")
              self.log_debug(error_msg)
        
        await asyncio.sleep(0.1)
    except Exception as e:
      error_msg = f"Error reading distlog samples: {e}"
      logging.error(f"[read_distlog_samples] {error_msg}")
      self.log_debug(error_msg)
  
  async def monitor_state(self):
    """Monitor distributed logger state"""
    try:
      state_endpoint = None
      for endpoint_key, endpoint in endpoints.items():
        if endpoint.p_key == self.participant_key and endpoint.topic_name == "rti/distlog/administration/state":
          state_endpoint = endpoint
          break
      
      if not state_endpoint or not state_endpoint.type:
        error_msg = "rti/distlog/administration/state topic not found or no type information available."
        self.state_output.update(error_msg)
        self.log_debug(error_msg)
        return
      
      if self.state_topic is None:
        try:
          self.state_topic = self.local_participant.find_topic("rti/distlog/administration/state")
          self.log_debug("Found existing state topic")
        except Exception as e:
          try:
            self.state_topic = dds.DynamicData.Topic(self.local_participant, "rti/distlog/administration/state", state_endpoint.type)
            self.log_debug("Created new state topic")
          except Exception as topic_error:
            error_msg = f"Failed to create state topic: {topic_error}"
            self.state_output.update(error_msg)
            self.log_debug(error_msg)
            logging.error(f"[monitor_state] {error_msg}")
            return
      
      filter_expression = "hostAndAppId.rtps_host_id = %0 AND hostAndAppId.rtps_app_id = %1"
      filter_parameters = [str(self.target_participant.rtps_host_id), str(self.target_participant.rtps_app_id)]
      
      filtered_topic_name = f"rti/distlog/administration/state_filtered_{self.target_participant.rtps_host_id}_{self.target_participant.rtps_app_id}"
      content_filtered_topic = dds.DynamicData.ContentFilteredTopic(
          self.state_topic,
          filtered_topic_name,
          dds.Filter(filter_expression, filter_parameters)
      )
      
      # DDS: Create subscriber with partition and presentation QoS if needed
      # Presentation QoS controls ordering and coherency of samples
      subscriber_qos = dds.SubscriberQos()
      qos_set = False
      
      if state_endpoint.partition:
        subscriber_qos.partition.name = state_endpoint.partition.name
        qos_set = True
      
      if state_endpoint.presentation:
        # Match presentation access_scope, coherent_access, and ordered_access
        subscriber_qos.presentation.access_scope = state_endpoint.presentation.access_scope
        subscriber_qos.presentation.coherent_access = state_endpoint.presentation.coherent_access
        subscriber_qos.presentation.ordered_access = state_endpoint.presentation.ordered_access
        qos_set = True
      
      if qos_set:
        self.state_subscriber = dds.Subscriber(self.local_participant, subscriber_qos)
      else:
        self.state_subscriber = dds.Subscriber(self.local_participant)
      
      # DDS: Configure reader QoS for compatibility with writer
      # Reader drives matching - request equal or "lower" QoS than writer offers
      # Durability: Match writer's TRANSIENT_LOCAL to receive historical state as late joiner
      # Deadline: Reader deadline must be >= writer deadline (less strict)
      # Ownership: Must match exactly (SHARED vs EXCLUSIVE)
      # Note: Full QoS matching shown here for reference - not all policies may be strictly necessary for this scenario
      reader_qos = dds.DataReaderQos()
      if state_endpoint.reliability:
        reader_qos.reliability.kind = state_endpoint.reliability.kind
        if state_endpoint.reliability.max_blocking_time:
          reader_qos.reliability.max_blocking_time = state_endpoint.reliability.max_blocking_time
      if state_endpoint.durability:
        reader_qos.durability.kind = state_endpoint.durability.kind
      if state_endpoint.deadline:
        reader_qos.deadline.period = state_endpoint.deadline.period
      if state_endpoint.ownership:
        reader_qos.ownership.kind = state_endpoint.ownership.kind
      
      self.state_reader = dds.DynamicData.DataReader(self.state_subscriber, content_filtered_topic, reader_qos)
      
      self.state_output.update("Subscribed to state topic. Waiting for state updates...")
      
      # DDS: Wait for TRANSIENT_LOCAL durability samples to arrive
      # Durability allows late-joining readers to receive historical samples
      # Multiple refresh attempts ensure we catch these samples
      await asyncio.sleep(0.5)
      max_attempts = 4
      for attempt in range(max_attempts):
        self.refresh_state_display()
        await asyncio.sleep(0.5)
      
    except Exception as e:
      error_msg = f"Error subscribing to state topic: {e}"
      self.state_output.update(error_msg)
      self.log_debug(error_msg)
      logging.error(f"[monitor_state] {e}")
  
  def refresh_state_display(self):
    """Refresh state display"""
    if self.state_reader is None:
      return
    
    try:
      samples = self.state_reader.take()
      for sample in samples:
        if sample.info.valid:
          try:
            member_names = list(sample.data.fields())
            lines = []
            
            # Extract hostAndAppId from the state for commanding
            if 'hostAndAppId' in member_names:
              host_app_id = sample.data['hostAndAppId']
              actual_host_id = host_app_id['rtps_host_id']
              actual_app_id = host_app_id['rtps_app_id']
              # Update target participant with correct values from state
              self.target_participant.rtps_host_id = actual_host_id
              self.target_participant.rtps_app_id = actual_app_id
              self.log_debug(f"Updated target host/app ID from state: {actual_host_id}/{actual_app_id}")
            
            for name in member_names:
              if name in ['hostAndAppId', 'administrationDomainId', 'state', 'rtiLoggerPrintFormat', 'applicationKind']:
                continue
              
              if name == 'filterLevel':
                level_value = sample.data[name]
                self.current_filter_level = level_value
                if self.filter_level_select:
                  # Temporarily disable to prevent triggering command on programmatic update
                  old_initialized = self.initialized
                  self.initialized = False
                  self.filter_level_select.value = level_value
                  self.initialized = old_initialized
                level_name = self.convert_verbosity_level(level_value)
                lines.append(f"{name}: {level_name} ({level_value})")
              elif name == 'rtiLoggerVerbosities':
                verbosities = sample.data[name]
                lines.append(f"{name}:")
                for item in verbosities:
                  lines.append(f"  {item['category']}: {item['verbosity']}")
              else:
                lines.append(f"{name}: {sample.data[name]}")
            
            state_text = "\n".join(lines)
            self.state_output.update(state_text)
          except Exception as e:
            logging.error(f"[refresh_state_display] Error processing sample: {e}")
    except Exception as e:
      logging.error(f"[refresh_state_display] {e}")
  
  def convert_verbosity_level(self, level):
    """Convert numeric verbosity level to string name"""
    verbosity_map = {
      0: "SILENT", 100: "FATAL", 200: "SEVERE", 300: "ERROR",
      400: "WARNING", 500: "NOTICE", 600: "INFO", 700: "DEBUG", 800: "TRACE"
    }
    return verbosity_map.get(level, f"UNKNOWN({level})")
  
  async def send_filter_level_command(self, filter_level):
    """Send filter level change command using DynamicData types discovered from builtin topics"""
    try:
      self.log_debug(f"Target participant: host_id={self.target_participant.rtps_host_id}, app_id={self.target_participant.rtps_app_id}")
      
      # DDS: Find command request/response topics from discovered endpoints for target participant
      # Focus on the target participant to ensure we're using the correct types/QoS
      request_endpoint = None
      response_endpoint = None
      
      for endpoint_key, endpoint in endpoints.items():
        if endpoint.p_key == self.participant_key:
          if endpoint.topic_name == "rti/distlog/administration/command_request":
            request_endpoint = endpoint
          elif endpoint.topic_name == "rti/distlog/administration/command_response":
            response_endpoint = endpoint
      
      if not request_endpoint or not request_endpoint.type:
        error_msg = f"Command request topic not found for target participant. Available: {[(e.topic_name, e.kind) for k,e in endpoints.items() if e.p_key == self.participant_key]}"
        self.log_debug(error_msg)
        return
      
      if not response_endpoint or not response_endpoint.type:
        error_msg = "Command response topic not found for target participant."
        self.log_debug(error_msg)
        return
      
      # DDS: Create CommandRequest using DynamicData
      # Get the type from the discovered endpoint
      request_type = request_endpoint.type
      command_request = dds.DynamicData(request_type)
      
      # Prepare values for command request
      target_host = self.target_participant.rtps_host_id
      target_app = self.target_participant.rtps_app_id
      self.log_debug(f"About to set: target_host={target_host}, target_app={target_app}")
      
      # DDS: Set nested struct fields using dot notation in bracket syntax
      # Format: data["struct_name.field_name"] for accessing nested members
      command_request["targetHostAndAppId.rtps_host_id"] = target_host
      command_request["targetHostAndAppId.rtps_app_id"] = target_app
      
      command_request["originatorHostAndAppId.rtps_host_id"] = 0
      command_request["originatorHostAndAppId.rtps_app_id"] = 0
      
      # Set invocation timestamp for response correlation
      invocation_timestamp = int(time.time())
      command_request["invocation"] = invocation_timestamp
      
      # DDS: Set union member - discriminator is automatically set when member is assigned
      # For unions in DynamicData, setting the member value implicitly sets the discriminator
      command_request["command.filterLevel"] = filter_level
      
      # DDS: Create topics using DynamicData with types from discovered endpoints
      # Create both request and response topics/entities upfront to allow discovery before sending
      request_topic = dds.DynamicData.Topic(
          self.local_participant,
          request_endpoint.topic_name,
          request_endpoint.type
      )
      
      response_topic = dds.DynamicData.Topic(
          self.local_participant,
          response_endpoint.topic_name,
          response_endpoint.type
      )
      
      # DDS: Match QoS policies from discovered endpoints
      # Create writer with same QoS as the target's command_request reader expects
      writer_qos = dds.DataWriterQos()
      if request_endpoint.reliability:
        writer_qos.reliability.kind = request_endpoint.reliability.kind
      if request_endpoint.durability:
        writer_qos.durability.kind = request_endpoint.durability.kind
      
      # DDS: Create publisher with matching partition QoS
      # Partitions act as logical communication channels - readers and writers
      # must be in matching partitions to communicate (like network VLANs)
      publisher = self.local_participant.implicit_publisher
      if request_endpoint.partition:
        pub_qos = dds.PublisherQos()
        pub_qos.partition.name = request_endpoint.partition.name
        publisher = dds.Publisher(self.local_participant, pub_qos)
      
      request_writer = dds.DynamicData.DataWriter(
          publisher,
          request_topic,
          writer_qos
      )
      
      # Create reader with same QoS as the target's command_response writer
      reader_qos = dds.DataReaderQos()
      if response_endpoint.reliability:
        reader_qos.reliability.kind = response_endpoint.reliability.kind
      if response_endpoint.durability:
        reader_qos.durability.kind = response_endpoint.durability.kind
      
      # Create subscriber with matching partition if needed
      subscriber = self.local_participant.implicit_subscriber
      if response_endpoint.partition:
        sub_qos = dds.SubscriberQos()
        sub_qos.partition.name = response_endpoint.partition.name
        subscriber = dds.Subscriber(self.local_participant, sub_qos)
      
      response_reader = dds.DynamicData.DataReader(
          subscriber,
          response_topic,
          reader_qos
      )
      
      # DDS: Wait for discovery to complete before sending command
      # Discovery is asynchronous - writers/readers must match before data exchange
      # publication_matched_status: tracks how many readers discovered this writer
      # subscription_matched_status: tracks how many writers discovered this reader
      # Creating both entities upfront ensures response reader is ready when reply arrives
      self.log_debug("Waiting for discovery...")
      discovery_timeout = 0
      while (request_writer.publication_matched_status.current_count == 0 or 
             response_reader.subscription_matched_status.current_count == 0) and discovery_timeout < 50:
        await asyncio.sleep(0.1)
        discovery_timeout += 1
      
      if request_writer.publication_matched_status.current_count == 0:
        error_msg = "No command subscriber found."
        self.log_debug(error_msg)
        return
      
      if response_reader.subscription_matched_status.current_count == 0:
        error_msg = "No command response publisher found."
        self.log_debug(error_msg)
        return
      
      self.log_debug(f"Discovery complete: request matched={request_writer.publication_matched_status.current_count}, response matched={response_reader.subscription_matched_status.current_count}")
      
      # DDS: Send command request using write()
      request_writer.write(command_request)
      self.log_debug(f"Sent filter level command: {filter_level}")
      
      # DDS: Poll for response using async pattern
      # datareader_cache_status.sample_count: number of samples available to read
      # In async contexts, polling is preferable to blocking WaitSet.wait()
      # take() retrieves and removes samples from reader's cache
      poll_count = 0
      max_polls = 300  # 30 seconds timeout
      
      while poll_count < max_polls:
        if response_reader.datareader_cache_status.sample_count > 0:
          responses = response_reader.take()
          for sample in responses:
            # DDS: Validate sample using SampleInfo
            if sample.info.valid:
              response_data = sample.data
              
              # DDS: Correlate response to request using invocation timestamp
              # In request-reply patterns, correlation ensures we match responses to requests
              # Check originator ID (0/0 = our request) and invocation timestamp
              originator = response_data["originatorHostAndAppId"]
              if (originator["rtps_host_id"] == 0 and 
                  originator["rtps_app_id"] == 0 and
                  response_data["invocation"] == invocation_timestamp):
                
                # Extract result and optional message
                command_result = response_data["commandResult"]
                try:
                  message = response_data["message"]
                except KeyError:
                  message = ""
                
                self.log_debug(f"Command reply: result={command_result}, message={message}")
                
                # CommandResult OK = 0 indicates success
                if command_result == 0:
                  self.refresh_state_display()
                return
        
        await asyncio.sleep(0.1)
        poll_count += 1
      
      self.log_debug("Command sent, but no response received (timeout).")
    except Exception as e:
      error_msg = f"Error sending command: {e}"
      self.log_debug(error_msg)
      logging.error(f"[send_filter_level_command] {e}")

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
    """Subscribe to discovered topic using DynamicData (no generated code required).
    
    DDS: DynamicData allows subscribing to topics without compile-time type support.
    The type is discovered via builtin topics and used to create a DynamicData.Topic.
    This enables generic monitoring tools like RTI Spy to work with any DDS type.
    """
    try:
      if not self.endpoint.type:
        self.output_widget.update("Error: No type information available for this topic.")
        return
      if not isinstance(self.endpoint.type, dds.DynamicType):
        self.output_widget.update("Error: Discovered type is not a DynamicType. Cannot subscribe with DynamicData.")
        return
      
      # DDS: Create topic using discovered DynamicType
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
      
      # DDS: Configure reader QoS to match discovered writer's QoS
      # QoS matching rules: reader can request "equal or less strict" QoS than writer offers
      # This ensures we receive data according to the writer's guarantees
      reader_qos = dds.DataReaderQos()
      
      if self.endpoint.reliability:
        reader_qos.reliability.kind = self.endpoint.reliability.kind
        reader_qos.reliability.max_blocking_time = self.endpoint.reliability.max_blocking_time
        
        if self.endpoint.durability:
          reader_qos.durability.kind = self.endpoint.durability.kind
        
        if self.endpoint.deadline:
          reader_qos.deadline.period = self.endpoint.deadline.period
        
        if self.endpoint.ownership:
          reader_qos.ownership.kind = self.endpoint.ownership.kind
        
        logging.info(f"[subscribe_topic] Applying QoS - Reliability: {self.endpoint.reliability.kind}, Durability: {self.endpoint.durability.kind if self.endpoint.durability else 'N/A'}, Ownership: {self.endpoint.ownership.kind if self.endpoint.ownership else 'N/A'}")
        
        # DDS: Create DynamicData DataReader with matched QoS
        dynamic_reader = dds.DynamicData.DataReader(subscriber, dynamic_topic, reader_qos)
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
            # DDS: Get writer handle from SampleInfo to identify the data source
            writer_handle = info.publication_handle

            # DDS: Get participant information for the matched writer
            # This shows which participant/application sent this data
            participant_data = dynamic_reader.matched_publication_participant_data(writer_handle)
            
            # Extract network location information for display
            ip_list = participant_data.default_unicast_locators[0].address[-4:]
            address_str = '.'.join(str(byte) for byte in ip_list)
            domain_id = participant_data.domain_id
            port = participant_data.default_unicast_locators[0].port
            topic_name = dynamic_reader.topic_name

            line = f"[{address_str}:{port} D:{domain_id}] {topic_name}: {data}"
            self.sample_lines.append(line)

            self.sample_lines = self.sample_lines[-20:]
            self.output_widget.update("\n".join(self.sample_lines))
    except Exception as e:
      self.output_widget.update(f"Error: {e}")


# DDS: Builtin topic listeners for automatic endpoint discovery
# These listeners are notified whenever a DataReader or DataWriter is discovered in the domain
class SubscriptionListener(dds.SubscriptionBuiltinTopicData.DataReaderListener):
  """Listener for DataReader discovery via DCPSSubscription builtin topic.
  
  DDS: The DCPSSubscription builtin topic publishes information about all DataReaders
  in the domain. By subscribing to it with a listener, we get automatic notifications
  whenever a new reader appears, changes QoS, or disappears.
  """
  def on_data_available(self, reader):
    for data, info in reader.take():
      if info.valid:
        # DDS: Extract unique key identifying this specific DataReader endpoint
        key_list = data.key.value
        key_string = str(key_list)

        type_name = data.type_name
        topic_name = data.topic_name

        # DDS: Get the participant key to associate this reader with its owning participant
        p_key_list = data.participant_key.value
        p_key_string = str(p_key_list)

        # DDS: Extract QoS policies - these determine communication behavior and matching rules
        # Matching: A writer and reader can only communicate if their QoS policies are compatible
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

class PublicationListener(dds.PublicationBuiltinTopicData.DataReaderListener):
  """Listener for DataWriter discovery via DCPSPublication builtin topic.
  
  DDS: The DCPSPublication builtin topic publishes information about all DataWriters
  in the domain. This enables automatic discovery of data sources and their QoS.
  """
  def on_data_available(self, reader):
    for data, info in reader.take():
      if info.valid:
        # DDS: Extract unique key identifying this specific DataWriter endpoint
        key_list = data.key.value
        key_string = str(key_list)

        type_name = data.type_name
        topic_name = data.topic_name

        # DDS: Get the participant key to associate this writer with its owning participant
        p_key_list = data.participant_key.value
        p_key_string = str(p_key_list)

        # DDS: Extract QoS policies from writer
        # These policies must be compatible with reader QoS for matching to occur
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
  BINDINGS = [ ("q", "quit", "Quit"), ("b", "back", "Back"), ("enter", "select", "Readers/Writers"), ("l", "logger", "Logger Dialog") ]


  def __init__(self, participant, interval=2.0):
    super().__init__()
    self.participant = participant
    self.interval = interval

  def compose(self) -> ComposeResult:
    # Yield a placeholder container; actual screens are pushed in on_mount
    yield Container()

  async def on_mount(self) -> None:
    # logging.debug("[on_mount] refreshing participants list")
    self.update_participants(self.participant)
    self.set_interval(self.interval, lambda: self.update_participants(self.participant))
    await self.push_screen(ParticipantListScreen(self, self.participant))


  def update_participants(self, participant):
    """Update the list of discovered participants in the domain.
    
    DDS: Uses the DCPSParticipant builtin topic to get information about all
    participants currently active in the domain. Called periodically to refresh.
    """
    # DDS: Get list of all discovered participant handles
    p_list = participant.discovered_participants()

    for p in p_list:
        # DDS: Get detailed data about each discovered participant
        data = participant.discovered_participant_data(p)
        name = data.participant_name.name
        
        # DDS: Extract IP address from unicast locator
        # Locators specify network addresses for communication
        ip_list = data.default_unicast_locators[0].address[-4:]
        ip = '.'.join(str(byte) for byte in ip_list)
        
        # DDS: Extract RTPS GUID components for unique participant identification
        # GUID = GuidPrefix (12 bytes) + EntityId (4 bytes)
        # GuidPrefix contains host_id and app_id in its first 8 bytes
        key_value = data.key.value  # Returns tuple of 4 integers
        
        if len(key_value) >= 2:
            rtps_host_id = key_value[0]
            rtps_app_id = key_value[1]
        else:
            rtps_host_id = 0
            rtps_app_id = 0

        participant_info = Participant(name, ip, rtps_host_id, rtps_app_id)
        key_string = str(key_value)
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

  # DDS: Create participant in disabled state to configure listeners before discovery starts
  # This ensures we don't miss any discovery events during initialization
  participant_factory_qos = dds.DomainParticipantFactoryQos()
  participant_factory_qos.entity_factory.autoenable_created_entities = False
  dds.DomainParticipant.participant_factory_qos = participant_factory_qos

  # DDS: Set participant name for easier identification in monitoring tools
  qos = dds.DomainParticipantQos()
  qos.participant_name.name = "RTI SPY"
  participant = dds.DomainParticipant(args.domain, qos=qos)

  # DDS: Attach listeners to builtin topic readers for automatic discovery notifications
  # publication_reader: notified when DataWriters are discovered
  # subscription_reader: notified when DataReaders are discovered
  participant.publication_reader.set_listener(PublicationListener(), dds.StatusMask.DATA_AVAILABLE)
  participant.subscription_reader.set_listener(SubscriptionListener(), dds.StatusMask.DATA_AVAILABLE)

  # DDS: Enable participant to start discovery and communication
  participant.enable()

  app = RTISPY(participant, interval=args.interval)
  app.run()

if __name__ == "__main__":
    main()