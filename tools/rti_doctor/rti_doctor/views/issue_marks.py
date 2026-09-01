"""Marking the endpoint rows a system finding names.

The endpoint lists are where an operator skims a system, and they said nothing
about which of those endpoints the Findings screen identifies - so
getting from "there is an ERROR on this domain" to the endpoint behind it meant
reading two screens and matching 4-word instance handles by eye.

Presentation only. What counts as a finding, and which endpoints one names, are
decided by the scan; this module decides what that looks like in a table.
"""

import asyncio
import logging
import time

from rich.text import Text

from .. import findings as f
from ..system_scan import SCAN_REUSE_SECONDS

#: Orange, not red. Red already means something in these screens - an action
#: that failed, a refresh that raised, a topology that never arrived - and a
#: marked row is a fact about the system, not a failure of the tool.
STYLE = "orange1"

#: WARN and above. Deliberately not INFO: `qos.no_counterpart` is a note that
#: every healthy single-writer domain produces, so marking notes would paint a
#: healthy system orange and leave the colour saying nothing.
FLOOR = f.Severity.WARN

SEVERITY_STYLE = {
    f.Severity.ERROR: "bold red",
    f.Severity.WARN: "bold yellow",
    f.Severity.INFO: "bold cyan",
    f.Severity.OK: "bold green",
}


def severity_text(value, severity):
  """A severity-coloured cell without parsing its value as Rich markup."""
  return Text(str(value), style=SEVERITY_STYLE.get(severity, ""))


def severity_summary(counts):
  """Trusted Rich markup for the three finding counts shown in status lines."""
  parts = []
  for severity, label in ((f.Severity.ERROR, "Errors"),
                          (f.Severity.WARN, "Warnings"),
                          (f.Severity.INFO, "Notes")):
    style = SEVERITY_STYLE[severity]
    parts.append(f"[{style}]{counts[severity]} {label}[/{style}]")
  return " | ".join(parts)


def severity_by_endpoint(snapshot, floor=FLOOR):
  """Worst finding severity at or above `floor`, per endpoint key.

  Both sides of a paired finding are marked. `qos.rxo_mismatch` names a writer AND
  a reader, and marking only the writer would say the reader is fine when the
  incompatibility is a property of the pair - which is also why this is keyed
  by endpoint key rather than by role.

  Marking both roles is the confirmed intent, not an over-reach of a
  writer-shaped request: do not narrow this to writers on the assumption that
  the reader case was an oversight.
  """
  marks = {}
  for issue in getattr(snapshot, "issues", ()) or ():
    if issue.severity < floor:
      continue
    for key in tuple(issue.writer_keys) + tuple(issue.reader_keys):
      marks[key] = max(marks.get(key, f.Severity.OK), issue.severity)
  return marks


async def marks_for(session, snapshot=None):
  """`severity_by_endpoint` for a screen being opened, reusing a recent scan.

  Awaitable because of the fallback: a scan is O(endpoints^2) in the topic
  census, and running it inline would block the event loop for as long as it
  takes on a large domain. Every other scan in the TUI is dispatched to a
  thread, and this is not the one place that should hold the UI still to colour
  some rows. A caller that already has a snapshot - both endpoint lists are
  reached from a screen that scanned to build itself - never reaches the thread
  at all.

  Never raises. These screens exist to list endpoints, so a scan that fails has
  to cost the operator the colour and not the list.
  """
  if snapshot is None:
    try:
      snapshot = await asyncio.to_thread(
          session.system_scan, None, SCAN_REUSE_SECONDS)
    except Exception as error:
      logging.error(f"[issue_marks] scan failed, rows left unmarked: {error}")
      return {}
  return severity_by_endpoint(snapshot)


def cells(values, severity=None):
  """One row's cells, orange when a system finding names this endpoint."""
  style = STYLE if severity else ""
  return [Text(str(value), style=style) for value in values]


def legend(severities, captured_at=None):
  """What the colour means, given one severity-or-None per rendered row.

  It names the count, because "some rows are orange" and "9 of 10 endpoints on
  this participant are in an ERROR" are different things to walk away with. The
  no-marks case is stated too: an operator who knows the domain has errors and
  sees no orange here needs to know that means "not these endpoints", rather
  than wondering whether the marking ran at all.
  """
  if not severities:
    return ""
  marked = [severity for severity in severities if severity]
  total = len(severities)
  # Scoped to when the scan was taken, always. The rows come from the live
  # registry and the marks come from a snapshot the caller took earlier, so an
  # endpoint that joined since - with the RxO mismatch that made it worth
  # opening this screen - is listed and unmarked. Present tense would make the
  # no-marks line a claim the snapshot cannot support.
  as_of = (f" as of the scan at {time.strftime('%H:%M:%S', time.localtime(captured_at))}"
           if captured_at else " as of the last system scan")
  if not marked:
    return (f"No system finding named any of these {total} endpoint(s) at "
            f"WARNING or above{as_of}. Notes are not marked.")
  errors = sum(1 for severity in marked if severity >= f.Severity.ERROR)
  warnings = len(marked) - errors
  counted = ", ".join(
      part for part in (f"{errors} in an ERROR" if errors else "",
                        f"{warnings} in a WARNING" if warnings else "") if part)
  return (f"[{STYLE}]Orange[/{STYLE}] = named by a system finding{as_of} "
          f"({counted}), {len(marked)} of {total} endpoint(s). Open its report "
          "for the finding.")
