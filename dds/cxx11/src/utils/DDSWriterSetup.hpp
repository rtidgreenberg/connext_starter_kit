/*
 * (c) Copyright, Real-Time Innovations, 2025.  All rights reserved.
 * RTI grants Licensee a license to use, modify, compile, and create derivative
 * works of the software solely for use with RTI Connext DDS. Licensee may
 * redistribute copies of the software provided that all such copies are subject
 * to this license. The software is provided "as is", with no warranty of any
 * type, including any warranty for fitness for any purpose. RTI is under no
 * obligation to maintain or support the software. RTI shall not be liable for
 * any incidental or consequential damages arising out of the use or inability
 * to use the software.
 */

#ifndef DDS_WRITER_SETUP_HPP
#define DDS_WRITER_SETUP_HPP

#include <rti/rti.hpp>  // Include necessary DDS headers
#include <string>       // Include string header
#include <iostream>

#include "DDSContextSetup.hpp"

using namespace rti::all;

template <typename T>
class DDSWriterSetup {
public:
    // Constructor accepting a DDSContextSetup for Writer setup
    explicit DDSWriterSetup(
            std::shared_ptr<DDSContextSetup> &context,
            const std::string &topic_name,
            const std::string &qos_file = "",
            const std::string &qos_profile = "")
            : _participant(context->participant()),
              _topic_name(topic_name),
              _qos_file(qos_file),
              _qos_profile(qos_profile)
    {
        std::cout << "Created DDS Writer Setup Class" << std::endl;

        if (!_qos_file.empty()) {
            _qos_provider = dds::core::QosProvider(_qos_file);
        }

        // If Topic not already created, create new
        _topic = dds::topic::find<dds::topic::Topic<T>>(
                _participant,
                _topic_name);
        if (_topic == dds::core::null) {
            _topic = dds::topic::Topic<T>(_participant, _topic_name);
        } else {
            std::cout << "Topic " << _topic_name << " already created"
                      << std::endl;
        }

        // Create DataWriter
        std::cout << "Creating Writer..." << std::endl;

        if (!_qos_file.empty() && !_qos_profile.empty()) {
            _writer = dds::pub::DataWriter<T>(
                    _topic,
                    _qos_provider.extensions().datawriter_qos_w_topic_name(
                            _qos_profile,
                            _topic_name));

            std::cout << "DataWriter created on topic: " << _topic_name
                      << " with QoS profile: " << _qos_profile << std::endl;
        } else {
            _writer = dds::pub::DataWriter<T>(_topic);
            std::cout << "DataWriter created on topic: " << _topic_name
                      << " with default QoS." << std::endl;
        }
    }

    // Getter for DataWriter
    dds::pub::DataWriter<T> writer() const
    {
        return _writer;
    }

    // Getter for Topic
    dds::topic::Topic<T> topic() const
    {
        return _topic;
    }

    // Getter for Topic Name
    const std::string &topic_name() const
    {
        return _topic_name;
    }

private:
    dds::domain::DomainParticipant _participant = dds::core::null;
    dds::pub::DataWriter<T> _writer = dds::core::null;
    dds::topic::Topic<T> _topic = dds::core::null;
    dds::core::QosProvider _qos_provider = dds::core::null;
    const std::string _topic_name;
    const std::string _qos_file;
    const std::string _qos_profile;
};

#endif  // DDS_WRITER_SETUP_HPP
