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
#include <rti/core/cond/AsyncWaitSet.hpp>
#include <string>       // Include string header
#include <iostream>
#include <functional>
#include <stdexcept>
#include "DDSContextSetup.hpp"

using namespace rti::all;


template <typename T>
class DDSWriterSetup {
public:
    // Define function types for status callbacks
    using PublicationMatchedFunction =
            std::function<void(dds::pub::DataWriter<T> &)>;
    
    using LivelinessLostFunction =
            std::function<void(dds::pub::DataWriter<T> &)>;
    
    using OfferedDeadlineMissedFunction =
            std::function<void(dds::pub::DataWriter<T> &)>;
    
    using OfferedIncompatibleQosFunction =
            std::function<void(dds::pub::DataWriter<T> &)>;

    // Constructor accepting a DDSContextSetup for Writer setup
    explicit DDSWriterSetup(
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
            _writer = dds::pub::DataWriter<T>(
                            _topic, 
                            dds::pub::qos::DataWriterQos());
                            
            std::cout << "DataWriter created on topic: " << _topic_name
                      << " with default QoS." << std::endl;
        }

        // Setup default status handler directly
        if (_writer != dds::core::null) {
            std::cout << "Setting up status condition for " << _topic_name << std::endl;
            _status_condition = dds::core::cond::StatusCondition(_writer);
            
            // Enable all writer status events
            _status_condition.enabled_statuses(
                dds::core::status::StatusMask::publication_matched()
                | dds::core::status::StatusMask::liveliness_lost()
                | dds::core::status::StatusMask::offered_deadline_missed()
                | dds::core::status::StatusMask::offered_incompatible_qos());
            
            // Attach handler directly - _on_status_triggered will dispatch
            _status_condition->handler([this](dds::core::cond::Condition) {
                _on_status_triggered();
            });
            
            // Attach to AsyncWaitSet
            try {
                _async_waitset.attach_condition(_status_condition);
                std::cout << "Attached status condition to AsyncWaitset for " << _topic_name << std::endl;
            } catch (const std::exception &e) {
                std::cerr << "Error attaching status condition: " << e.what() << std::endl;
            }
            
            // Start the AsyncWaitSet
            _async_waitset.start();
        }
    }

    // Destructor - detach conditions from AsyncWaitSet
    ~DDSWriterSetup()
    {
        try {
            // Detach status condition if it was attached
            if (_status_condition != dds::core::null) {
                _async_waitset.detach_condition(_status_condition);
                std::cout << "Detached status condition for " << _topic_name << std::endl;
            }
        } catch (const std::exception &e) {
            std::cerr << "Error detaching status condition: " << e.what() << std::endl;
        }

        std::cout << "DDSWriterSetup destroyed for topic: " << _topic_name << std::endl;
    }

    // Set handler for publication matched events
    void set_publication_matched_handler(PublicationMatchedFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting publication matched handler for " << _topic_name << std::endl;
        _publication_matched_callback = handler;
    }

    // Set handler for liveliness lost events
    void set_liveliness_lost_handler(LivelinessLostFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting liveliness lost handler for " << _topic_name << std::endl;
        _liveliness_lost_callback = handler;
    }

    // Set handler for offered deadline missed events
    void set_offered_deadline_missed_handler(OfferedDeadlineMissedFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting offered deadline missed handler for " << _topic_name << std::endl;
        _offered_deadline_missed_callback = handler;
    }

    // Set handler for offered incompatible QoS events
    void set_offered_incompatible_qos_handler(OfferedIncompatibleQosFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting offered incompatible QoS handler for " << _topic_name << std::endl;
        _offered_incompatible_qos_callback = handler;
    }

    // Wait indefinitely for a number of DataReaders to match
    void wait_for_drs_to_match(int expected_dr_matches)
    {
        if (expected_dr_matches <= 0) {
            throw std::invalid_argument(
                    "Error: expected_dr_matches must be greater than 0");
        }

        std::cout << "Waiting indefinitely for DataReaders to match with the DataWriter..." << std::endl;

        while (_writer.publication_matched_status().current_count() < expected_dr_matches
            && !application::shutdown_requested) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        std::cout << "DataWriter matched with " +
                std::to_string(_writer.publication_matched_status().current_count()) +
                " DataReaders" << std::endl;
    };

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

    // Default handler for publication matched events
    void _default_on_publication_matched()
    {
        auto status = _writer.publication_matched_status();
        
        std::cout << "[Writer] Publication matched event for topic: " 
                  << _writer.topic().name() << std::endl;
        std::cout << "  Current count: " << status.current_count() << std::endl;
        std::cout << "  Current count change: " << status.current_count_change() 
                  << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() 
                  << std::endl;
    }

    // Default handler for liveliness lost events
    void _default_on_liveliness_lost()
    {
        auto status = _writer.liveliness_lost_status();
        
        std::cout << "[Writer] Liveliness lost event for topic: " 
                  << _writer.topic().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
    }

    // Default handler for offered deadline missed events
    void _default_on_offered_deadline_missed()
    {
        auto status = _writer.offered_deadline_missed_status();
        
        std::cout << "[Writer] Offered deadline missed event for topic: " 
                  << _writer.topic().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
    }

    // Default handler for offered incompatible QoS events
    void _default_on_offered_incompatible_qos()
    {
        auto status = _writer.offered_incompatible_qos_status();
        
        std::cout << "[Writer] Offered incompatible QoS event for topic: " 
                  << _writer.topic().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
        std::cout << "  Last policy: " << status.last_policy_id() << std::endl;
    }

    // Handler that checks which status triggered and dispatches accordingly
    void _on_status_triggered()
    {
        auto status_mask = _writer.status_changes();
        
        // Check if publication matched status triggered
        if ((status_mask & dds::core::status::StatusMask::publication_matched()).any()) {
            if (_publication_matched_callback) {
                _publication_matched_callback(_writer);
            } else {
                _default_on_publication_matched();
            }
        }
        
        // Check if liveliness lost status triggered
        if ((status_mask & dds::core::status::StatusMask::liveliness_lost()).any()) {
            if (_liveliness_lost_callback) {
                _liveliness_lost_callback(_writer);
            } else {
                _default_on_liveliness_lost();
            }
        }
        
        // Check if offered deadline missed status triggered
        if ((status_mask & dds::core::status::StatusMask::offered_deadline_missed()).any()) {
            if (_offered_deadline_missed_callback) {
                _offered_deadline_missed_callback(_writer);
            } else {
                _default_on_offered_deadline_missed();
            }
        }
        
        // Check if offered incompatible QoS status triggered
        if ((status_mask & dds::core::status::StatusMask::offered_incompatible_qos()).any()) {
            if (_offered_incompatible_qos_callback) {
                _offered_incompatible_qos_callback(_writer);
            } else {
                _default_on_offered_incompatible_qos();
            }
        }
    }

    dds::domain::DomainParticipant _participant = dds::core::null;

    // Async Waitset - reference to the one owned by DDSContextSetup
    rti::core::cond::AsyncWaitSet &_async_waitset;

    dds::pub::DataWriter<T> _writer = dds::core::null;
    dds::topic::Topic<T> _topic = dds::core::null;
    dds::core::cond::StatusCondition _status_condition = dds::core::null;
    dds::core::QosProvider _qos_provider = dds::core::null;
    const std::string _topic_name;
    const std::string _qos_file;
    const std::string _qos_profile;

    // Registered status callbacks
    PublicationMatchedFunction _publication_matched_callback;
    LivelinessLostFunction _liveliness_lost_callback;
    OfferedDeadlineMissedFunction _offered_deadline_missed_callback;
    OfferedIncompatibleQosFunction _offered_incompatible_qos_callback;
};

#endif  // DDS_WRITER_SETUP_HPP
