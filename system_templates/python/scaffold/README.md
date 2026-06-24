# Python Scaffold Templates

These parameterized templates generate DDS processes using the **Python asyncio** pattern
with `rti.connextdds` and `rti.asyncio` for asynchronous data processing.

## Files

| Template | Generated As | Purpose |
|---|---|---|
| `app_main.py.template` | `apps/python/<process>/<name>.py` | DDS infrastructure + async event loop |
| `process_logic.py.template` | `apps/python/<process>/<name>_logic.py` | Business logic class |
| `requirements.txt.template` | `apps/python/<process>/requirements.txt` | Python dependencies |
| `run.sh.template` | `apps/python/<process>/run.sh` | Launch script with venv + NDDSHOME |

## Pattern

The Python scaffold follows the same clean architecture as C++:

```
app_main.py          ← DDS infrastructure (participant, readers, writers, asyncio)
<name>_logic.py      ← Business logic (callbacks, compute functions, no DDS imports)
```

### Async Architecture

- Each DataReader has a **subscriber coroutine** using `reader.take_data_async()`
- Each DataWriter has a **publisher coroutine** with periodic `writer.write()`
- All coroutines are launched with `asyncio.gather()` and controlled by a `shutdown_event`
- Signal handlers (SIGINT/SIGTERM) set the `shutdown_event` for graceful shutdown

## Substitution Variables

### Identity
- `{{PROCESS_NAME}}` — snake_case
- `{{PROCESS_NAME_PASCAL}}` — PascalCase
- `{{APP_DISPLAY_NAME}}` — human-readable

### DDS Configuration
- `{{DEFAULT_DOMAIN_ID}}` — from system_config.yaml
- `{{QOS_PROFILE}}` — profile URI for QosProvider
- `{{IMPORTS}}` — `import` statements for generated IDL types

### Generated Blocks
- `{{READER_SETUP}}` — DataReader creation code
- `{{WRITER_SETUP}}` — DataWriter creation code
- `{{SUBSCRIBER_COROUTINES}}` — async reader coroutine definitions
- `{{PUBLISHER_COROUTINES}}` — async writer coroutine definitions
- `{{COROUTINE_LAUNCHES}}` — `asyncio.create_task()` calls

### Logic Layer
- `{{CALLBACK_METHODS}}` — subscriber callback method stubs
- `{{COMPUTE_METHODS}}` — publisher compute method stubs
- `{{STATE_INIT}}` — `__init__` state variables
