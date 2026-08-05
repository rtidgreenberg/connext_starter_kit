#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <thread>

#include <fastdds/dds/domain/DomainParticipant.hpp>
#include <fastdds/dds/domain/DomainParticipantFactory.hpp>
#include <fastdds/dds/publisher/DataWriter.hpp>
#include <fastdds/dds/publisher/DataWriterListener.hpp>
#include <fastdds/dds/publisher/Publisher.hpp>
#include <fastdds/dds/subscriber/DataReader.hpp>
#include <fastdds/dds/subscriber/DataReaderListener.hpp>
#include <fastdds/dds/subscriber/Subscriber.hpp>
#include <fastdds/dds/subscriber/SampleInfo.hpp>
#include <fastdds/dds/topic/Topic.hpp>
#include <fastdds/dds/topic/TypeSupport.hpp>

#include "HelloWorld.hpp"
#include "HelloWorldPubSubTypes.hpp"
#include "HelloWorldTypeObjectSupport.hpp"

using namespace eprosima::fastdds::dds;

class NoTypeMetadataHelloWorldPubSubType : public HelloWorldPubSubType {
public:
    void register_type_object_representation() override
    {
    }
};

struct WriterListener : DataWriterListener {
    std::atomic<int> matched{0};
    void on_publication_matched(DataWriter*, const PublicationMatchedStatus& status) override
    {
        matched.store(status.current_count);
    }
};

struct ReaderListener : DataReaderListener {
    std::atomic<int> matched{0};
    std::atomic<int> samples{0};
    void on_subscription_matched(DataReader*, const SubscriptionMatchedStatus& status) override
    {
        matched.store(status.current_count);
    }
    void on_data_available(DataReader* reader) override
    {
        HelloWorld sample;
        SampleInfo info;
        while (reader->take_next_sample(&sample, &info) == RETCODE_OK)
        {
            if (info.valid_data)
            {
                samples.fetch_add(1);
            }
        }
    }
};

int main(int argc, char** argv)
{
    int domain = -1;
    std::string topic_name;
    std::string role;
    std::string extensibility;
    std::string reliability = "reliable";
    std::string durability = "volatile";
    int deadline_seconds = 1;
    std::string ownership = "shared";
    std::string representation = "xcdr1";
    std::string type_metadata = "full";
    std::string type_lookup = "disabled";
    std::string wait_for_file;
    std::string endpoint_ready_file;
    int duration_seconds = 6;
    int wait_timeout_seconds = 15;
    for (int index = 1; index < argc; ++index)
    {
        std::string argument(argv[index]);
        if ((argument == "--domain" || argument == "--topic" || argument == "--role" ||
             argument == "--duration" || argument == "--extensibility" ||
             argument == "--reliability" || argument == "--durability" ||
             argument == "--deadline-seconds" ||
             argument == "--ownership" ||
             argument == "--representation" ||
             argument == "--type-metadata" ||
             argument == "--type-lookup" || argument == "--wait-for-file" ||
             argument == "--wait-timeout" || argument == "--endpoint-ready-file") && index + 1 < argc)
        {
            std::string value(argv[++index]);
            if (argument == "--domain") domain = std::stoi(value);
            if (argument == "--topic") topic_name = value;
            if (argument == "--role") role = value;
            if (argument == "--duration") duration_seconds = std::stoi(value);
            if (argument == "--extensibility") extensibility = value;
            if (argument == "--reliability") reliability = value;
            if (argument == "--durability") durability = value;
            if (argument == "--deadline-seconds") deadline_seconds = std::stoi(value);
            if (argument == "--ownership") ownership = value;
            if (argument == "--representation") representation = value;
            if (argument == "--type-metadata") type_metadata = value;
            if (argument == "--type-lookup") type_lookup = value;
            if (argument == "--wait-for-file") wait_for_file = value;
            if (argument == "--wait-timeout") wait_timeout_seconds = std::stoi(value);
            if (argument == "--endpoint-ready-file") endpoint_ready_file = value;
        }
    }
    if (domain < 0 || topic_name.empty() || duration_seconds <= 0 ||
            wait_timeout_seconds <= 0 ||
            (role != "writer" && role != "reader") ||
            (extensibility != "final" && extensibility != "appendable") ||
            (reliability != "reliable" && reliability != "best-effort") ||
            (durability != "volatile" && durability != "transient-local") ||
            deadline_seconds <= 0 ||
            (ownership != "shared" && ownership != "exclusive") ||
            (representation != "xcdr1" && representation != "xcdr2") ||
            (type_metadata != "full" && type_metadata != "none") ||
            (type_lookup != "enabled" && type_lookup != "disabled"))
    {
        std::cerr << "required: --domain --topic --role writer|reader --duration positive "
                  << "--extensibility final|appendable "
                  << "[--reliability reliable|best-effort] "
                  << "[--durability volatile|transient-local] "
                  << "[--deadline-seconds positive] "
                  << "[--ownership shared|exclusive] "
                  << "[--representation xcdr1|xcdr2] "
                  << "[--type-metadata full|none] "
                  << "[--type-lookup enabled|disabled] "
                  << "[--wait-for-file PATH] [--wait-timeout positive] "
                  << "[--endpoint-ready-file PATH]" << std::endl;
        return 2;
    }

    DomainParticipantQos participant_qos = PARTICIPANT_QOS_DEFAULT;
    DomainParticipant* participant = DomainParticipantFactory::get_instance()->create_participant(
        static_cast<uint32_t>(domain), participant_qos);
    if (participant == nullptr)
    {
        return 3;
    }

    if (!wait_for_file.empty())
    {
        const auto deadline = std::chrono::steady_clock::now() +
                std::chrono::seconds(wait_timeout_seconds);
        while (std::chrono::steady_clock::now() < deadline)
        {
            std::ifstream start_signal(wait_for_file);
            if (start_signal.good())
            {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(25));
        }
        std::ifstream start_signal(wait_for_file);
        if (!start_signal.good())
        {
            std::cerr << "timed out waiting for start signal: " << wait_for_file << std::endl;
            DomainParticipantFactory::get_instance()->delete_participant(participant);
            return 11;
        }
    }

    TypeSupport type(type_metadata == "none"
            ? static_cast<TopicDataType*>(new NoTypeMetadataHelloWorldPubSubType())
            : static_cast<TopicDataType*>(new HelloWorldPubSubType()));
    if (type.register_type(participant, "DoctorExtensibility::Sample") !=
            RETCODE_OK)
    {
        std::cerr << "failed to register DoctorExtensibility::Sample" << std::endl;
        DomainParticipantFactory::get_instance()->delete_participant(participant);
        return 4;
    }
    Topic* topic = participant->create_topic(topic_name, "DoctorExtensibility::Sample", TOPIC_QOS_DEFAULT);
    if (topic == nullptr)
    {
        DomainParticipantFactory::get_instance()->delete_participant(participant);
        return 5;
    }

    int samples = 0;
    int matched = 0;
    if (role == "writer")
    {
        Publisher* publisher = participant->create_publisher(PUBLISHER_QOS_DEFAULT);
        if (publisher == nullptr)
        {
            std::cerr << "failed to create publisher" << std::endl;
            participant->delete_topic(topic);
            DomainParticipantFactory::get_instance()->delete_participant(participant);
            return 6;
        }
        DataWriterQos qos = DATAWRITER_QOS_DEFAULT;
        qos.representation().m_value = {representation == "xcdr2"
            ? XCDR2_DATA_REPRESENTATION : XCDR_DATA_REPRESENTATION};
        qos.reliability().kind = reliability == "reliable"
            ? RELIABLE_RELIABILITY_QOS : BEST_EFFORT_RELIABILITY_QOS;
        qos.durability().kind = durability == "transient-local"
            ? TRANSIENT_LOCAL_DURABILITY_QOS : VOLATILE_DURABILITY_QOS;
        qos.deadline().period = {deadline_seconds, 0u};
        qos.ownership().kind = ownership == "exclusive"
            ? EXCLUSIVE_OWNERSHIP_QOS : SHARED_OWNERSHIP_QOS;
        WriterListener listener;
        DataWriter* writer = publisher->create_datawriter(topic, qos, &listener);
        if (writer == nullptr)
        {
            std::cerr << "failed to create data writer" << std::endl;
            participant->delete_publisher(publisher);
            participant->delete_topic(topic);
            DomainParticipantFactory::get_instance()->delete_participant(participant);
            return 7;
        }
        if (!endpoint_ready_file.empty())
        {
            std::ofstream endpoint_ready_signal(endpoint_ready_file);
            endpoint_ready_signal << "ready\n";
        }
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(duration_seconds);
        HelloWorld sample;
        sample.message("DoctorExtensibility");
        while (std::chrono::steady_clock::now() < deadline)
        {
            sample.index(static_cast<uint32_t>(++samples));
            if (writer->write(&sample) != RETCODE_OK)
            {
                std::cerr << "failed to write sample" << std::endl;
                publisher->delete_datawriter(writer);
                participant->delete_publisher(publisher);
                participant->delete_topic(topic);
                DomainParticipantFactory::get_instance()->delete_participant(participant);
                return 8;
            }
            matched = std::max(matched, listener.matched.load());
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        publisher->delete_datawriter(writer);
        participant->delete_publisher(publisher);
    }
    else
    {
        Subscriber* subscriber = participant->create_subscriber(SUBSCRIBER_QOS_DEFAULT);
        if (subscriber == nullptr)
        {
            std::cerr << "failed to create subscriber" << std::endl;
            participant->delete_topic(topic);
            DomainParticipantFactory::get_instance()->delete_participant(participant);
            return 9;
        }
        DataReaderQos qos = DATAREADER_QOS_DEFAULT;
        qos.representation().m_value = {representation == "xcdr2"
            ? XCDR2_DATA_REPRESENTATION : XCDR_DATA_REPRESENTATION};
        qos.reliability().kind = reliability == "reliable"
            ? RELIABLE_RELIABILITY_QOS : BEST_EFFORT_RELIABILITY_QOS;
        qos.durability().kind = durability == "transient-local"
            ? TRANSIENT_LOCAL_DURABILITY_QOS : VOLATILE_DURABILITY_QOS;
        qos.deadline().period = {deadline_seconds, 0u};
        qos.ownership().kind = ownership == "exclusive"
            ? EXCLUSIVE_OWNERSHIP_QOS : SHARED_OWNERSHIP_QOS;
        ReaderListener listener;
        DataReader* reader = subscriber->create_datareader(topic, qos, &listener);
        if (reader == nullptr)
        {
            std::cerr << "failed to create data reader" << std::endl;
            participant->delete_subscriber(subscriber);
            participant->delete_topic(topic);
            DomainParticipantFactory::get_instance()->delete_participant(participant);
            return 10;
        }
        if (!endpoint_ready_file.empty())
        {
            std::ofstream endpoint_ready_signal(endpoint_ready_file);
            endpoint_ready_signal << "ready\n";
        }
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(duration_seconds);
        while (std::chrono::steady_clock::now() < deadline)
        {
            matched = std::max(matched, listener.matched.load());
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
        samples = listener.samples.load();
        subscriber->delete_datareader(reader);
        participant->delete_subscriber(subscriber);
    }

    participant->delete_topic(topic);
    DomainParticipantFactory::get_instance()->delete_participant(participant);
    std::cout << "{\"vendor\":\"fastdds\",\"role\":\"" << role
              << "\",\"extensibility\":\"" << extensibility
              << "\",\"reliability\":\"" << reliability
              << "\",\"durability\":\"" << durability
              << "\",\"deadline_seconds\":" << deadline_seconds
              << ",\"ownership\":\"" << ownership
              << "\",\"representation\":\"" << representation
              << "\",\"type_metadata\":\"" << type_metadata
              << "\",\"type_lookup\":\"" << type_lookup
              << "\",\"results\":{\"matched\":" << matched
              << ",\"samples\":" << samples << "}}" << std::endl;
    return 0;
}
