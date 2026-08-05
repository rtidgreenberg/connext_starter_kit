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
  domains = {selected_domain_id}
  domains.update(domain for domain in active_domain_ids or () if domain is not None)
  return {
      "source": "builtin discovery",
      "scope": "remote entities observed while RTI Doctor was running",
      "selected_domain_id": selected_domain_id,
      "domain_ids": sorted(domains),
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