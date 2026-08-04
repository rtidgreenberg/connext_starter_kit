#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
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

#include "HelloWorld.h"
#include "HelloWorldPubSubTypes.h"
#include "HelloWorldTypeObject.h"

using namespace eprosima::fastdds::dds;

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
        while (reader->take_next_sample(&sample, &info) == ReturnCode_t::RETCODE_OK)
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
    int duration_seconds = 6;
    for (int index = 1; index < argc; ++index)
    {
        std::string argument(argv[index]);
        if ((argument == "--domain" || argument == "--topic" || argument == "--role" ||
             argument == "--duration" || argument == "--extensibility") && index + 1 < argc)
        {
            std::string value(argv[++index]);
            if (argument == "--domain") domain = std::stoi(value);
            if (argument == "--topic") topic_name = value;
            if (argument == "--role") role = value;
            if (argument == "--duration") duration_seconds = std::stoi(value);
            if (argument == "--extensibility") extensibility = value;
        }
    }
    if (domain < 0 || topic_name.empty() || duration_seconds <= 0 ||
            (role != "writer" && role != "reader") ||
            (extensibility != "final" && extensibility != "appendable"))
    {
        std::cerr << "required: --domain --topic --role writer|reader --duration positive "
                  << "--extensibility final|appendable" << std::endl;
        return 2;
    }

    registerHelloWorldTypes();
    DomainParticipant* participant = DomainParticipantFactory::get_instance()->create_participant(
        static_cast<uint32_t>(domain), PARTICIPANT_QOS_DEFAULT);
    if (participant == nullptr)
    {
        return 3;
    }

    TypeSupport type(new HelloWorldPubSubType());
    if (type.register_type(participant, "DoctorExtensibility::Sample") !=
            ReturnCode_t::RETCODE_OK)
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
        qos.representation().m_value = {XCDR_DATA_REPRESENTATION};
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
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(duration_seconds);
        HelloWorld sample;
        sample.message("DoctorExtensibility");
        while (std::chrono::steady_clock::now() < deadline)
        {
            sample.index(static_cast<uint32_t>(++samples));
            if (!writer->write(&sample))
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
        qos.type_consistency().representation.m_value = {XCDR_DATA_REPRESENTATION};
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
              << "\",\"results\":{\"matched\":" << matched
              << ",\"samples\":" << samples << "}}" << std::endl;
    return 0;
}
