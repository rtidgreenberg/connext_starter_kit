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

#ifndef DDS_INTERFACE_HPP
#define DDS_INTERFACE_HPP

#include <rti/rti.hpp>  // Include necessary DDS headers
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <string>  // Include string header
#include <unordered_map>
#include <mutex>
#include <iostream>
#include <functional>

#include "DDSContext.hpp"

using namespace rti::all;

// Enum class for data kind
enum class KIND {
    WRITER,  // Writer - data flows out
    READER   // Reader - data flows in
};


template <typename T>
class DDSInterface {
public:
    // Define function type for data processing callback
    using DataProcessingFunction =
            std::function<void(dds::sub::DataReader<T> &)>;

    // Constructor accepting a DDSContext and KIND
    explicit DDSInterface(
            std::shared_ptr<DDSContext> &context,
            KIND kind,
            const std::string &TopicName,
            const std::string &qos_file = "",
            const std::string &qos_profile = "")
            : _participant(context->participant()),
              _async_waitset(context->async_waitset()),
              _kind(kind),
              _topic_name(TopicName),
              _qos_file(qos_file),
              _qos_profile(qos_profile)
    {
        std::cout << "Created DDS Interface Class" << std::endl;

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

        // Switch statement based on kind
        switch (kind) {
        case KIND::WRITER:
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

            break;
        case KIND::READER:
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

            break;
        default:
            std::cerr << "Invalid KIND provided" << std::endl;
            break;
        }
    }

    void enable_async_waitset(DataProcessingFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No data handler provided for AsyncWaitSet"
                      << std::endl;
            return;
        }

        _custom_data_handler = handler;
        std::cout << "Enabling AsyncWaitSet for DDSInterface " << _topic_name
                  << " with custom handler" << std::endl;

        // Setup status conditions
        if (_reader != dds::core::null) {
            std::cout << "Setting Condition\n";
            _condition = dds::core::cond::StatusCondition(_reader);
        }

        if (_kind == KIND::READER) {
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
        } else {
            std::cerr << "Error: Attempt to enable Async Waitset on Writer "
                         "Interface"
                      << std::endl;
            return;
        }
    }

    // Getter for KIND
    KIND kind()
    {
        return _kind;
    }

    // Getter for DataWriter - returns valid writer only for WRITER interfaces
    dds::pub::DataWriter<T> writer() const
    {
        if (_kind != KIND::WRITER) {
            std::cerr
                    << "Warning: Attempting to get writer from READER interface"
                    << std::endl;
        }
        return _writer;
    }

    // Getter for DataReader - returns valid reader only for READER interfaces
    dds::sub::DataReader<T> reader() const
    {
        if (_kind != KIND::READER) {
            std::cerr
                    << "Warning: Attempting to get reader from WRITER interface"
                    << std::endl;
        }
        return _reader;
    }

private:
    dds::domain::DomainParticipant _participant = dds::core::null;

    // Async Waitset - reference to the one owned by DDSContext
    rti::core::cond::AsyncWaitSet &_async_waitset;

    KIND _kind;

    dds::pub::DataWriter<T> _writer = dds::core::null;
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


#endif  // DDS_INTERFACE_HPP