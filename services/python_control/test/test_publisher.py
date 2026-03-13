"""
Simple DDS publisher for end-to-end testing.
Publishes a few samples on a test topic so Recording Service has data to record.
"""
import time
import rti.connextdds as dds


def publish_test_data(domain_id=0, num_samples=20, interval=0.5):
    """Publish test data on domain 0."""

    # Build a simple type
    test_type = dds.StructType("TestMessage")
    test_type.add_member(dds.Member("id", dds.Int32Type()))
    test_type.add_member(dds.Member("message", dds.StringType(256)))
    test_type.add_member(dds.Member("value", dds.Float64Type()))

    participant = dds.DomainParticipant(domain_id)
    topic = dds.DynamicData.Topic(participant, "TestTopic", test_type)
    writer = dds.DynamicData.DataWriter(participant.implicit_publisher, topic)

    print(f"[TestPublisher] Publishing {num_samples} samples on "
          f"domain {domain_id}, topic 'TestTopic'...")

    for i in range(num_samples):
        sample = dds.DynamicData(test_type)
        sample["id"] = i
        sample["message"] = f"test message {i}"
        sample["value"] = i * 1.5
        writer.write(sample)
        print(f"  Published sample {i}")
        time.sleep(interval)

    print("[TestPublisher] Done publishing.")
    participant.close()


if __name__ == "__main__":
    publish_test_data()
