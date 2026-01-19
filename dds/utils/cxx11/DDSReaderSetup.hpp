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

#include "DDSParticipantSetup.hpp"

using namespace rti::all;

/*
 * DDSReaderSetup Class
 * 
 * Manages DataReader creation and event-driven callback processing:
 *   - DataReader: Subscribes to messages on a specified topic with configurable QoS
 *   - Status Callbacks: Supports multiple DDS event callbacks including:
 *       * data_available: Fires when new data is available to read
 *       * subscription_matched: Fires when writers matching the subscription are discovered
 *       * liveliness_changed: Fires when writer liveliness status changes
 *       * requested_deadline_missed: Fires when expected data deadline is missed
 *       * requested_incompatible_qos: Fires when QoS requirements are incompatible
 *       * sample_lost: Fires when samples are lost due to resource constraints
 *       * sample_rejected: Fires when samples are rejected by the reader
 *   - AsyncWaitSet Integration: Registers status conditions with the centralized AsyncWaitSet
 *                                allowing all status events to be processed asynchronously via
 *                                thread pool without blocking the application
 */
template <typename T>
class DDSReaderSetup {
public:
    // Define function type for data processing callback
    using DataProcessingFunction =
            std::function<void(dds::sub::DataReader<T> &)>;

    // Define function type for subscription matched callback
    using SubscriptionMatchedFunction =
            std::function<void(dds::sub::DataReader<T> &)>;

    // Define function type for other status callbacks
    using LivelinessChangedFunction =
            std::function<void(dds::sub::DataReader<T> &)>;
    
    using RequestedDeadlineMissedFunction =
            std::function<void(dds::sub::DataReader<T> &)>;
    
    using RequestedIncompatibleQosFunction =
            std::function<void(dds::sub::DataReader<T> &)>;
    
    using SampleLostFunction =
            std::function<void(dds::sub::DataReader<T> &)>;
    
    using SampleRejectedFunction =
            std::function<void(dds::sub::DataReader<T> &)>;

    // Constructor accepting a DDSParticipantSetup for Reader setup
    explicit DDSReaderSetup(
            std::shared_ptr<DDSParticipantSetup> &p_setup,
            const std::string &topic_name,
            const std::string &qos_profile = "")
            : _participant(p_setup->participant()),
              _async_waitset(p_setup->async_waitset()),
              _topic_name(topic_name),
              _qos_file(p_setup->qos_file_path()),
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

        // Setup default status handler directly
        if (_reader != dds::core::null) {
            std::cout << "Setting up status condition for " << _topic_name << std::endl;
            _status_condition = dds::core::cond::StatusCondition(_reader);
            
            // Enable subscription matched status
            _status_condition.enabled_statuses(
                dds::core::status::StatusMask::subscription_matched()
                | dds::core::status::StatusMask::liveliness_changed()
                | dds::core::status::StatusMask::requested_deadline_missed()
                | dds::core::status::StatusMask::requested_incompatible_qos()
                | dds::core::status::StatusMask::sample_lost()
                | dds::core::status::StatusMask::sample_rejected());
            
            // Attach handler directly - on_status_triggered will dispatch
            _status_condition->handler([this](dds::core::cond::Condition) {
                on_status_triggered();
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
    ~DDSReaderSetup()
    {
        try {
            // Detach read condition if it was attached
            if (_read_condition != dds::core::null) {
                _async_waitset.detach_condition(_read_condition);
                std::cout << "Detached read condition for " << _topic_name << std::endl;
            }
        } catch (const std::exception &e) {
            std::cerr << "Error detaching read condition: " << e.what() << std::endl;
        }

        try {
            // Detach status condition if it was attached
            if (_status_condition != dds::core::null) {
                _async_waitset.detach_condition(_status_condition);
                std::cout << "Detached status condition for " << _topic_name << std::endl;
            }
        } catch (const std::exception &e) {
            std::cerr << "Error detaching status condition: " << e.what() << std::endl;
        }

        std::cout << "DDSReaderSetup destroyed for topic: " << _topic_name << std::endl;
    }

    // Set data handler and attach read condition with NOT_READ state to AsyncWaitSet
    void set_data_available_handler(DataProcessingFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No data handler provided" << std::endl;
            return;
        }

        _custom_data_handler = handler;
        std::cout << "Setting data handler for " << _topic_name << std::endl;

        // Detach old read condition if it exists
        if (_read_condition != dds::core::null) {
            try {
                _async_waitset.detach_condition(_read_condition);
                std::cout << "Detached previous read condition\n";
            } catch (const std::exception &e) {
                std::cerr << "Error detaching previous read condition: " << e.what() << std::endl;
            }
        }

        // Create read condition with NOT_READ sample state
        if (_reader != dds::core::null) {
            std::cout << "Creating ReadCondition with NOT_READ sample state\n";
            _read_condition = dds::sub::cond::ReadCondition(
                _reader,
                dds::sub::status::DataState(
                    dds::sub::status::SampleState::not_read(),
                    dds::sub::status::ViewState::any(),
                    dds::sub::status::InstanceState::any()
                )
            );
        } else {
            std::cerr << "Error: Reader is null, cannot create ReadCondition" << std::endl;
            return;
        }

        std::cout << "Configuring read condition handler" << std::endl;

        // Add the registered handler to be triggered when new data comes in
        _read_condition->handler([this](dds::core::cond::Condition) {
            _custom_data_handler(_reader);
        });

        // Attach condition to AsyncWaitSet
        std::cout << "Attaching read condition to AsyncWaitset\n";
        try {
            _async_waitset.attach_condition(_read_condition);
        } catch (const std::exception &e) {
            std::cerr << "Error attaching read condition: " << e.what() << '\n';
            return;
        }

        std::cout << "Data handler configured for " << _topic_name << std::endl;

        // Start - returns true if already started
        _async_waitset.start();
    }

    // Set handler for subscription matched events
    void set_subscription_matched_handler(SubscriptionMatchedFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting subscription matched handler for " << _topic_name << std::endl;
        
        // Store the custom handler
        _subscription_matched_callback = handler;
    }

    // Set handler for liveliness changed events
    void set_liveliness_changed_handler(LivelinessChangedFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting liveliness changed handler for " << _topic_name << std::endl;
        _liveliness_changed_callback = handler;
    }

    // Set handler for requested deadline missed events
    void set_requested_deadline_missed_handler(RequestedDeadlineMissedFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting requested deadline missed handler for " << _topic_name << std::endl;
        _requested_deadline_missed_callback = handler;
    }

    // Set handler for requested incompatible QoS events
    void set_requested_incompatible_qos_handler(RequestedIncompatibleQosFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting requested incompatible QoS handler for " << _topic_name << std::endl;
        _requested_incompatible_qos_callback = handler;
    }

    // Set handler for sample lost events
    void set_sample_lost_handler(SampleLostFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting sample lost handler for " << _topic_name << std::endl;
        _sample_lost_callback = handler;
    }

    // Set handler for sample rejected events
    void set_sample_rejected_handler(SampleRejectedFunction handler)
    {
        if (!handler) {
            std::cerr << "Error: No handler provided" << std::endl;
            return;
        }

        std::cout << "Setting sample rejected handler for " << _topic_name << std::endl;
        _sample_rejected_callback = handler;
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
    // Default callback for subscription matched events
    void default_on_subscription_matched()
    {
        auto status = _reader.subscription_matched_status();
        
        std::cout << "[Reader] Subscription matched event for topic: " 
                  << _reader.topic_description().name() << std::endl;
        std::cout << "  Current count: " << status.current_count() << std::endl;
        std::cout << "  Current count change: " << status.current_count_change() 
                  << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() 
                  << std::endl;
    }

    // Default callback for liveliness changed events
    void default_on_liveliness_changed()
    {
        auto status = _reader.liveliness_changed_status();
        
        std::cout << "[Reader] Liveliness changed event for topic: " 
                  << _reader.topic_description().name() << std::endl;
        std::cout << "  Alive count: " << status.alive_count() << std::endl;
        std::cout << "  Alive count change: " << status.alive_count_change() << std::endl;
        std::cout << "  Not alive count: " << status.not_alive_count() << std::endl;
        std::cout << "  Not alive count change: " << status.not_alive_count_change() << std::endl;
    }

    // Default callback for requested deadline missed events
    void default_on_requested_deadline_missed()
    {
        auto status = _reader.requested_deadline_missed_status();
        
        std::cout << "[Reader] Requested deadline missed event for topic: " 
                  << _reader.topic_description().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
    }

    // Default callback for requested incompatible QoS events
    void default_on_requested_incompatible_qos()
    {
        auto status = _reader.requested_incompatible_qos_status();
        
        std::cout << "[Reader] Requested incompatible QoS event for topic: " 
                  << _reader.topic_description().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
        std::cout << "  Last policy: " << status.last_policy_id() << std::endl;
    }

    // Default callback for sample lost events
    void default_on_sample_lost()
    {
        auto status = _reader.sample_lost_status();
        
        std::cout << "[Reader] Sample lost event for topic: " 
                  << _reader.topic_description().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
    }

    // Default callback for sample rejected events
    void default_on_sample_rejected()
    {
        auto status = _reader.sample_rejected_status();
        
        std::cout << "[Reader] Sample rejected event for topic: " 
                  << _reader.topic_description().name() << std::endl;
        std::cout << "  Total count: " << status.total_count() << std::endl;
        std::cout << "  Total count change: " << status.total_count_change() << std::endl;
        std::cout << "  Last reason: " << status.last_reason().to_string() << std::endl;
    }

    // Handler that checks which status triggered and dispatches accordingly
    void on_status_triggered()
    {
        auto status_mask = _reader.status_changes();
        
        // Check if subscription matched status triggered
        if ((status_mask & dds::core::status::StatusMask::subscription_matched()).any()) {
            // Call custom callback if registered, otherwise use default
            if (_subscription_matched_callback) {
                _subscription_matched_callback(_reader);
            } else {
                default_on_subscription_matched();
            }
        }
        
        // Check if liveliness changed status triggered
        if ((status_mask & dds::core::status::StatusMask::liveliness_changed()).any()) {
            if (_liveliness_changed_callback) {
                _liveliness_changed_callback(_reader);
            } else {
                default_on_liveliness_changed();
            }
        }
        
        // Check if requested deadline missed status triggered
        if ((status_mask & dds::core::status::StatusMask::requested_deadline_missed()).any()) {
            if (_requested_deadline_missed_callback) {
                _requested_deadline_missed_callback(_reader);
            } else {
                default_on_requested_deadline_missed();
            }
        }
        
        // Check if requested incompatible QoS status triggered
        if ((status_mask & dds::core::status::StatusMask::requested_incompatible_qos()).any()) {
            if (_requested_incompatible_qos_callback) {
                _requested_incompatible_qos_callback(_reader);
            } else {
                default_on_requested_incompatible_qos();
            }
        }
        
        // Check if sample lost status triggered
        if ((status_mask & dds::core::status::StatusMask::sample_lost()).any()) {
            if (_sample_lost_callback) {
                _sample_lost_callback(_reader);
            } else {
                default_on_sample_lost();
            }
        }
        
        // Check if sample rejected status triggered
        if ((status_mask & dds::core::status::StatusMask::sample_rejected()).any()) {
            if (_sample_rejected_callback) {
                _sample_rejected_callback(_reader);
            } else {
                default_on_sample_rejected();
            }
        }
    }

    dds::domain::DomainParticipant _participant = dds::core::null;

    // Async Waitset - reference to the one owned by DDSContextSetup
    rti::core::cond::AsyncWaitSet &_async_waitset;

    dds::sub::DataReader<T> _reader = dds::core::null;
    dds::topic::Topic<T> _topic = dds::core::null;
    dds::sub::cond::ReadCondition _read_condition = dds::core::null;
    dds::core::cond::StatusCondition _status_condition = dds::core::null;
    dds::core::QosProvider _qos_provider = dds::core::null;
    const std::string _topic_name;
    const std::string _qos_file;
    const std::string _qos_profile;

    // Custom data processing function
    DataProcessingFunction _custom_data_handler;
    
    // Registered status callbacks
    SubscriptionMatchedFunction _subscription_matched_callback;
    LivelinessChangedFunction _liveliness_changed_callback;
    RequestedDeadlineMissedFunction _requested_deadline_missed_callback;
    RequestedIncompatibleQosFunction _requested_incompatible_qos_callback;
    SampleLostFunction _sample_lost_callback;
    SampleRejectedFunction _sample_rejected_callback;
};

#endif  // DDS_READER_SETUP_HPP
