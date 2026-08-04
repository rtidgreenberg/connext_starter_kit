"""Passive discovery of which DDS domain IDs currently have active participants.

Ported from rti_spy's scan_active_domains(), including its findings, because the
same behavior underpins rti_doctor's `blind.other_domain_active` check: seeing a
participant announce from a *different* domain is what turns an empty table from
"nothing is here" into "you picked the wrong domain".
"""

import logging
import time

import rti.connextdds as dds


def scan_active_domains(timeout=32.0, progress_callback=None):
  """Passively discover which DDS domain IDs currently have active participants.

  RTI Connext participants send a "default domain announcement" (an RTPX-magic
  packet, see community.rti.com/kb/why-do-i-see-packet-starts-rtpx-instead-rtps)
  to domain 0's default discovery multicast address/port (239.255.0.1:7400)
  regardless of which domain they actually run in. This is controlled by
  DiscoveryConfigQosPolicy.default_domain_announcement_period (default: 30s,
  enabled by default) and lets a single domain-0 listener discover the
  domain_id of participants running on other domains.

  This creates a temporary domain-0 participant with
  ignore_default_domain_announcements=False, listens for `timeout` seconds,
  and returns the set of domain IDs seen in the participant built-in reader's
  ParticipantBuiltinTopicData samples. `progress_callback`, if given, is
  called periodically as `progress_callback(elapsed_seconds, timeout,
  domain_ids_so_far)` so callers can show liveness during a long scan.

  Two things were confirmed empirically against a live 7.7.0 install and are
  NOT well documented:

  1. Cross-domain RTPX announcements only surface through the participant
     built-in reader (participant.participant_reader.take()/.read()). They
     are NOT included in participant.discovered_participants() /
     discovered_participant_data(), which only reflects normal same-domain
     SPDP matching and stayed empty in testing even while
     participant_reader.take() correctly saw the remote domain_id.
  2. A remote participant only sends its announcement on creation and then
     every `default_domain_announcement_period` (30s default) afterward -
     there is no periodic "catch-up" resend for a listener that starts
     later. So for an already-running remote participant, our scan window
     starts at an arbitrary phase of its 30s cycle and may need to wait
     nearly the full 30s to see it. `timeout` therefore defaults to just
     over one full period (32s) to make detection of already-running
     domains close to guaranteed rather than a coin flip.

  Best-effort only: participants that disable UDPv4 discovery, use a custom
  multicast address, or disabled their own default_domain_announcement_period
  won't be seen. This is an important caveat for the blind-spot audit: an empty
  result is NOT proof that no other domain is active.
  """
  qos = dds.DomainParticipantQos()
  try:
    qos.discovery_config.ignore_default_domain_announcements = False
  except Exception as e:
    # Older versions may not expose this; the scan then only sees domain 0.
    logging.warning(f"[scan_active_domains] Cannot disable announcement filtering: {e}")

  domain_ids = set()
  try:
    participant = dds.DomainParticipant(0, qos=qos)
  except Exception as e:
    logging.warning(f"[scan_active_domains] Could not create scan participant: {e}")
    return domain_ids

  try:
    start = time.monotonic()
    deadline = start + timeout
    while time.monotonic() < deadline:
      for sample in participant.participant_reader.take():
        if not sample.info.valid:
          continue
        try:
          domain_ids.add(sample.data.domain_id)
        except Exception as e:
          logging.debug(f"[scan_active_domains] Skipping unreadable participant data: {e}")
      if progress_callback is not None:
        try:
          progress_callback(time.monotonic() - start, timeout, domain_ids)
        except Exception as e:
          logging.debug(f"[scan_active_domains] progress_callback failed: {e}")
      time.sleep(0.2)
  finally:
    try:
      participant.close()
    except Exception as e:
      logging.warning(f"[scan_active_domains] Error closing scan participant: {e}")

  return domain_ids
