# (c) Copyright, Real-Time Innovations, 2026.  All rights reserved.
# RTI grants Licensee a license to use, modify, compile, and create derivative
# works of the software solely for use with RTI Connext DDS. Licensee may
# redistribute copies of the software provided that all such copies are subject
# to this license. The software is provided "as is", with no warranty of any
# type, including any warranty for fitness for any purpose. RTI is under no
# obligation to maintain or support the software. RTI shall not be liable for
# any incidental or consequential damages arising out of the use or inability
# to use the software.
"""Low-impact DDS topology snapshots derived from Doctor's discovery registry."""


def snapshot(registry, selected_domain_id, active_domain_ids=(),
             domain_scan_ran=False):
  """Return observed remote topology without creating a packet capture.

  Builtin-topic discovery is Doctor's primary topology source: it is already
  needed for diagnosis and avoids copying or parsing unrelated host traffic.
  Counts are an observation at report time, not a claim of a complete historic
  domain census when Doctor joined after endpoints were announced.
  """
  participants = registry.participant_list() if registry is not None else []
  writers = registry.writers() if registry is not None else []
  readers = registry.readers() if registry is not None else []
  topics = sorted({endpoint.topic_name for endpoint in writers + readers
                   if endpoint.topic_name})
  # Kept separate from the selected domain on purpose. Every count below comes
  # from a registry that only ever sees ONE domain; merging the domains the
  # passive scan heard announcing into a single "domain_ids" list printed those
  # other domains directly above counts that say nothing about them.
  other_domains = sorted({domain for domain in active_domain_ids or ()
                          if domain is not None and domain != selected_domain_id})
  return {
      "source": "builtin discovery",
      "scope": "remote entities observed while RTI Doctor was running",
      "selected_domain_id": selected_domain_id,
      "other_domains_announcing": other_domains,
      "domain_scan_ran": bool(domain_scan_ran),
      "participants": len(participants),
      "writers": len(writers),
      "readers": len(readers),
      "topics": topics,
      "topic_count": len(topics),
      "complete": False,
      "completion_note": (
          "A late-starting observer can miss already-announced endpoints. "
          "Use the optional 32-second passive domain scan to wait for the "
          "next default-domain announcement; it identifies active domains "
          "but cannot reconstruct endpoint announcements that were not replayed."
      ),
  }