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

#ifndef DDS_READER_SETUP_HPP
#define DDS_READER_SETUP_HPP

#include <rti/rti.hpp>  // Include necessary DDS headers
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <string>      // Include string header
#include <iostream>
#include <functional>

#include "DDSContextSetup.hpp"

using namespace rti::all;

template <typename T>
class DDSReaderSetup {
public:
    // Define function type for data processing callback
    using DataProcessingFunction =
            std::function<void(dds::sub::DataReader<T> &)>;

    // Constructor accepting a DDSContextSetup for Reader setup
    explicit DDSReaderSetup(
            std::shared_ptr<DDSContextSetup> &context,
            const std::string &topic_name,
            const std::string &qos_file = "",
            const std::string &qos_profile = "")
            : _participant(context->participant()),
              _async_waitset(context->async_waitset()),
              _topic_name(topic_name),
              _qos_file(qos_file),
              _qos_profile(qos_profile)
    {
        std::cout << "Created DDS Reader Setup Class" << std::endl;

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

        // Create DataReader
        std::cout << "Creating Reader..." << std::endl;

        if (!_qos_file.empty() && !_qos_profile.empty()) {
            _reader = dds::sub::DataReader<T>(
                    _topic,
                    _qos_provider.extensions().datareader_qos_w_topic_name(
                            _qos_profile,
                            _topic_name));

            std::cout << "DataReader created on topic: " << _topic_name
                      << " with QoS profile: " << _qos_profile << std::endl;
        } else {
            _reader = dds::sub::DataReader<T>(_topic);
            std::cout << "DataReader created on topic: " << _topic_name
                      << " with default QoS." << std::endl;
        }
    }

    // Enable AsyncWaitSet for event-driven data processing
    void enable_async_waitset(DataProcessingFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No data handler provided for AsyncWaitSet"
                      << std::endl;
            return;
        }

        _custom_data_handler = handler;
        std::cout << "Enabling AsyncWaitSet for DDSReaderSetup " << _topic_name
                  << " with custom handler" << std::endl;

        // Setup status conditions
        if (_reader != dds::core::null) {
            std::cout << "Setting Condition\n";
            _condition = dds::core::cond::StatusCondition(_reader);
        }

        std::cout << "Configuring AsyncWaitSet for Reader" << std::endl;

        _condition.enabled_statuses(
                dds::core::status::StatusMask::data_available());

        // Add the registered handler to be triggered when new data comes in
        _condition->handler([this](dds::core::cond::Condition) {
            _custom_data_handler(_reader);
        });

        // Attach conditions. The Async Waitset will be triggered when the
        // attached conditions are triggered.
        std::cout << "Setting up Async Waitset\n";
        try {
            _async_waitset.attach_condition(_condition);
        } catch (const std::exception &e) {
            std::cerr << e.what() << '\n';
        }

        std::cout << "AsyncWaitSet configured with data available "
                     "condition for "
                  << _topic_name << std::endl;

        // Start - returns true if already started
        _async_waitset.start();
    }

    // Getter for DataReader
    dds::sub::DataReader<T> reader() const
    {
        return _reader;
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

    // Async Waitset - reference to the one owned by DDSContextSetup
    rti::core::cond::AsyncWaitSet &_async_waitset;

    dds::sub::DataReader<T> _reader = dds::core::null;
    dds::topic::Topic<T> _topic = dds::core::null;
    dds::core::cond::StatusCondition _condition = dds::core::null;
    dds::core::QosProvider _qos_provider = dds::core::null;
    const std::string _topic_name;
    const std::string _qos_file;
    const std::string _qos_profile;

    // Custom data processing function
    DataProcessingFunction _custom_data_handler;
};

#endif  // DDS_READER_SETUP_HPP
