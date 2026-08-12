"""Deterministic, port-safe DDS domain selection for the test suites.

Every suite used to pick its domain with `random.randint` over its own private
base and span. Two consequences, both of which make a red run ambiguous - and an
ambiguous red is one a developer learns to ignore:

  * A collision with another run, or with anything else on the network, is
    indistinguishable from the fault the test was written to detect. Because it
    is random, it is also not reproducible from the failure output.
  * Some bases reached domain 230, whose RTPS ports sit just under the 16-bit
    ceiling. `DOMAIN_BASE = 210 + randint(1, 20)` was one wrapped port away from
    a failure with no plausible connection to DDS.

So: derive the domain from a stable key, and refuse to return one whose port
range is not valid and unprivileged.

`RTI_DOCTOR_DOMAIN_OFFSET` shifts the whole band. Determinism is what makes a
failure reproducible, but it also means two developers on one network would now
collide every time instead of occasionally - so each machine (or CI runner) can
claim its own band without touching the tests.
"""

import hashlib
import os

#: The interoperable DDS-RTPS defaults. A domain's ports are
#: [PORT_BASE + DOMAIN_GAIN*d, PORT_BASE + DOMAIN_GAIN*(d+1) - 1].
PORT_BASE = 7400
DOMAIN_GAIN = 250

MIN_UNPRIVILEGED_PORT = 1024
MAX_PORT = 65535

#: Domains below this are left to humans and to whatever else is on the network;
#: 0 and 1 especially, since they are the defaults every tool reaches for.
FIRST_TEST_DOMAIN = 20


def port_range(domain_id):
  """(first, last) UDP port this domain's RTPS traffic can occupy."""
  first = PORT_BASE + DOMAIN_GAIN * domain_id
  return first, first + DOMAIN_GAIN - 1


def is_safe(domain_id):
  """True when every port this domain can use is valid and unprivileged."""
  if domain_id < 0:
    return False
  first, last = port_range(domain_id)
  return MIN_UNPRIVILEGED_PORT <= first and last <= MAX_PORT


def last_safe_domain():
  """Highest domain whose whole port range fits under the 16-bit ceiling."""
  return (MAX_PORT - (DOMAIN_GAIN - 1) - PORT_BASE) // DOMAIN_GAIN


def offset():
  """Per-machine band shift, from RTI_DOCTOR_DOMAIN_OFFSET (default 0)."""
  try:
    return int(os.environ.get("RTI_DOCTOR_DOMAIN_OFFSET", "0"))
  except ValueError:
    return 0


def for_suite(key):
  """A stable, port-safe domain for `key` - normally a module or test name.

  The same key always yields the same domain, so a failure can be reproduced
  from the test name alone, and two suites with different keys are very unlikely
  to share one.
  """
  first, last = FIRST_TEST_DOMAIN, last_safe_domain()
  span = last - first + 1
  digest = hashlib.sha256(str(key).encode("utf-8")).digest()
  candidate = first + (int.from_bytes(digest[:4], "big") + offset()) % span

  if not is_safe(candidate):  # unreachable via the span above; belt and braces
    raise AssertionError(
        f"domain {candidate} for '{key}' has an unusable RTPS port range "
        f"{port_range(candidate)}")
  return candidate
