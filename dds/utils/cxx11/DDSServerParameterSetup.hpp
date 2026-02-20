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

#ifndef DDS_SERVER_PARAMETER_SETUP_HPP
#define DDS_SERVER_PARAMETER_SETUP_HPP

#include <rti/rti.hpp>

#include <string>
#include <map>
#include <vector>
#include <functional>
#include <iostream>
#include <algorithm>

#include "DDSParticipantSetup.hpp"
#include "DDSParameterUtils.hpp"
#include "ExampleTypes.hpp"
#include "Definitions.hpp"

using namespace rti::all;

/*
 * DDSServerParameterSetup
 * 
 * Parameter server using pure DDS API with Content Filtered Topics:
 *   - CFT filters requests by node_id at the middleware level
 *   - Uses AsyncWaitSet with ReadConditions for async processing
 *   - Pure DDS DataReader/DataWriter entities
 * 
 * Usage:
 *   DDSServerParameterSetup server(participant, "my_node");
 *   server.set_parameters(params);  // Auto-publishes event
 */
class DDSServerParameterSetup {
public:
    using SetParametersCallback = std::function<example_types::SetParametersResponse(
        const example_types::SetParametersRequest&)>;

    /**
     * Create a parameter server for the given node name.
     * Sets up CFT readers and writers for all parameter services.
     * 
     * @param participant_setup  Shared participant with AsyncWaitSet
     * @param node_name          This node's name (used in CFT filter)
     * @param callback           Optional custom handler for SetParameters requests
     * @param qos_profile        QoS profile for pub/sub
     */
    explicit DDSServerParameterSetup(
            std::shared_ptr<DDSParticipantSetup>& participant_setup,
            const std::string& node_name,
            SetParametersCallback callback = nullptr,
            const std::string& qos_profile = qos_profiles::ASSIGNER)
        : _participant_setup(participant_setup),
          _node_name(node_name),
          _qos_profile(qos_profile),
          _server_callback(callback)
    {
        setup_endpoints();
        std::cout << "[DDSServerParameterSetup] Ready: " << _node_name 
                  << " (using CFT filter)" << std::endl;
    }

    ~DDSServerParameterSetup()
    {
        // Detach read conditions from AsyncWaitSet
        auto& aws = _participant_setup->async_waitset();
        
        if (_set_read_condition != dds::core::null) {
            aws.detach_condition(_set_read_condition);
        }
        if (_get_read_condition != dds::core::null) {
            aws.detach_condition(_get_read_condition);
        }
        if (_list_read_condition != dds::core::null) {
            aws.detach_condition(_list_read_condition);
        }
        
        std::cout << "[DDSServerParameterSetup] Destroyed: " << _node_name << std::endl;
    }

    //--------------------------------------------------------------------------
    // Parameter Storage
    //--------------------------------------------------------------------------

    void set_parameter(const example_types::Parameter& param)
    {
        std::string name(param.name());
        bool is_new = (_parameters.find(name) == _parameters.end());
        _parameters[name] = param;
        
        if (is_new) {
            _pending_new.push_back(param);
        } else {
            _pending_changed.push_back(param);
        }
    }

    void set_parameters(const std::vector<example_types::Parameter>& params)
    {
        for (const auto& p : params) {
            set_parameter(p);
        }
        publish_event();
    }

    bool has_parameter(const std::string& name) const
    {
        return _parameters.find(name) != _parameters.end();
    }

    const example_types::Parameter& get_parameter(const std::string& name) const
    {
        return _parameters.at(name);
    }

    std::vector<example_types::Parameter> get_all_parameters() const
    {
        std::vector<example_types::Parameter> result;
        for (const auto& kv : _parameters) {
            result.push_back(kv.second);
        }
        return result;
    }

    void delete_parameter(const std::string& name)
    {
        auto it = _parameters.find(name);
        if (it != _parameters.end()) {
            _pending_deleted.push_back(it->second);
            _parameters.erase(it);
        }
        publish_event();
    }

    size_t parameter_count() const { return _parameters.size(); }

    const std::string& node_name() const { return _node_name; }

    std::vector<std::string> list_parameter_names(const std::string& prefix = "", uint32_t depth = 0) const
    {
        std::vector<std::string> names;
        for (const auto& kv : _parameters) {
            if (prefix.empty() || kv.first.find(prefix) == 0) {
                if (depth > 0) {
                    size_t dots = std::count(kv.first.begin(), kv.first.end(), '.');
                    if (dots >= depth) continue;
                }
                names.push_back(kv.first);
            }
        }
        return names;
    }

    //--------------------------------------------------------------------------
    // Event Publishing
    //--------------------------------------------------------------------------

    void publish_event()
    {
        if (_pending_new.empty() && _pending_changed.empty() && _pending_deleted.empty()) {
            return;
        }

        example_types::ParameterEvent event;
        event.node_id(_node_name);
        event.timestamp_ns(DDSParameterUtils::current_timestamp_ns());
        
        for (const auto& p : _pending_new) {
            event.new_parameters().push_back(p);
        }
        for (const auto& p : _pending_changed) {
            event.changed_parameters().push_back(p);
        }
        for (const auto& p : _pending_deleted) {
            event.deleted_parameters().push_back(p);
        }

        _event_writer.write(event);
        
        _pending_new.clear();
        _pending_changed.clear();
        _pending_deleted.clear();
    }

private:
    void setup_endpoints()
    {
        auto& participant = _participant_setup->participant();
        auto& aws = _participant_setup->async_waitset();
        
        // Get QoS provider
        dds::core::QosProvider qos_provider(
            _participant_setup->qos_file_path(), 
            _qos_profile);
        
        //----------------------------------------------------------------------
        // Create Topics
        //----------------------------------------------------------------------
        _event_topic = dds::topic::Topic<example_types::ParameterEvent>(
            participant, topics::PARAMETER_EVENTS_TOPIC);
        
        _set_request_topic = dds::topic::Topic<example_types::SetParametersRequest>(
            participant, topics::SET_PARAMETERS_REQUEST_TOPIC);
        _set_response_topic = dds::topic::Topic<example_types::SetParametersResponse>(
            participant, topics::SET_PARAMETERS_RESPONSE_TOPIC);
        
        _get_request_topic = dds::topic::Topic<example_types::GetParametersRequest>(
            participant, topics::GET_PARAMETERS_REQUEST_TOPIC);
        _get_response_topic = dds::topic::Topic<example_types::GetParametersResponse>(
            participant, topics::GET_PARAMETERS_RESPONSE_TOPIC);
        
        _list_request_topic = dds::topic::Topic<example_types::ListParametersRequest>(
            participant, topics::LIST_PARAMETERS_REQUEST_TOPIC);
        _list_response_topic = dds::topic::Topic<example_types::ListParametersResponse>(
            participant, topics::LIST_PARAMETERS_RESPONSE_TOPIC);

        //----------------------------------------------------------------------
        // Create Content Filtered Topics for requests (filter by node_id)
        //----------------------------------------------------------------------
        std::vector<std::string> filter_params = { "'" + _node_name + "'" };
        dds::topic::Filter filter("node_id = %0", filter_params);
        
        _set_request_cft = dds::topic::ContentFilteredTopic<example_types::SetParametersRequest>(
            _set_request_topic,
            _node_name + "_SetRequest_CFT",
            filter);
        
        _get_request_cft = dds::topic::ContentFilteredTopic<example_types::GetParametersRequest>(
            _get_request_topic,
            _node_name + "_GetRequest_CFT",
            filter);
        
        _list_request_cft = dds::topic::ContentFilteredTopic<example_types::ListParametersRequest>(
            _list_request_topic,
            _node_name + "_ListRequest_CFT",
            filter);

        std::cout << "[Server " << _node_name << "] CFT filter: node_id = '" 
                  << _node_name << "'" << std::endl;

        //----------------------------------------------------------------------
        // Create Writers (responses + events) with topic-aware QoS
        //----------------------------------------------------------------------
        dds::pub::Publisher publisher(participant);
        
        _event_writer = dds::pub::DataWriter<example_types::ParameterEvent>(
            publisher, _event_topic, 
            qos_provider.extensions().datawriter_qos_w_topic_name(topics::PARAMETER_EVENTS_TOPIC));
        
        _set_response_writer = dds::pub::DataWriter<example_types::SetParametersResponse>(
            publisher, _set_response_topic, 
            qos_provider.extensions().datawriter_qos_w_topic_name(topics::SET_PARAMETERS_RESPONSE_TOPIC));
        
        _get_response_writer = dds::pub::DataWriter<example_types::GetParametersResponse>(
            publisher, _get_response_topic, 
            qos_provider.extensions().datawriter_qos_w_topic_name(topics::GET_PARAMETERS_RESPONSE_TOPIC));
        
        _list_response_writer = dds::pub::DataWriter<example_types::ListParametersResponse>(
            publisher, _list_response_topic, 
            qos_provider.extensions().datawriter_qos_w_topic_name(topics::LIST_PARAMETERS_RESPONSE_TOPIC));

        //----------------------------------------------------------------------
        // Create Readers on CFTs with topic-aware QoS (only receive requests for this node)
        //----------------------------------------------------------------------
        dds::sub::Subscriber subscriber(participant);
        
        _set_request_reader = dds::sub::DataReader<example_types::SetParametersRequest>(
            subscriber, _set_request_cft, 
            qos_provider.extensions().datareader_qos_w_topic_name(topics::SET_PARAMETERS_REQUEST_TOPIC));
        
        _get_request_reader = dds::sub::DataReader<example_types::GetParametersRequest>(
            subscriber, _get_request_cft, 
            qos_provider.extensions().datareader_qos_w_topic_name(topics::GET_PARAMETERS_REQUEST_TOPIC));
        
        _list_request_reader = dds::sub::DataReader<example_types::ListParametersRequest>(
            subscriber, _list_request_cft, 
            qos_provider.extensions().datareader_qos_w_topic_name(topics::LIST_PARAMETERS_REQUEST_TOPIC));

        //----------------------------------------------------------------------
        // Create ReadConditions and attach to AsyncWaitSet
        //----------------------------------------------------------------------
        dds::sub::status::DataState new_data_state(
            dds::sub::status::SampleState::not_read(),
            dds::sub::status::ViewState::any(),
            dds::sub::status::InstanceState::any());

        _set_read_condition = dds::sub::cond::ReadCondition(
            _set_request_reader, new_data_state);
        _set_read_condition->handler([this](dds::core::cond::Condition) {
            handle_set_requests();
        });
        aws.attach_condition(_set_read_condition);

        _get_read_condition = dds::sub::cond::ReadCondition(
            _get_request_reader, new_data_state);
        _get_read_condition->handler([this](dds::core::cond::Condition) {
            handle_get_requests();
        });
        aws.attach_condition(_get_read_condition);

        _list_read_condition = dds::sub::cond::ReadCondition(
            _list_request_reader, new_data_state);
        _list_read_condition->handler([this](dds::core::cond::Condition) {
            handle_list_requests();
        });
        aws.attach_condition(_list_read_condition);

        // Ensure AsyncWaitSet is started
        aws.start();
    }

    void handle_set_requests()
    {
        auto samples = _set_request_reader.take();
        for (const auto& sample : samples) {
            if (!sample.info().valid()) continue;
            
            // CFT already filtered by node_id
            const auto& request = sample.data();
            
            example_types::SetParametersResponse response;
            
            if (_server_callback) {
                response = _server_callback(request);
            } else {
                response = default_set_handler(request);
            }
            
            _set_response_writer.write(response);
        }
    }

    void handle_get_requests()
    {
        auto samples = _get_request_reader.take();
        for (const auto& sample : samples) {
            if (!sample.info().valid()) continue;
            
            // CFT already filtered by node_id
            const auto& request = sample.data();
            
            example_types::GetParametersResponse response;
            response.node_id(_node_name);
            response.request_id(request.request_id());
            
            for (const auto& name : request.names()) {
                std::string param_name(name);
                if (has_parameter(param_name)) {
                    response.parameters().push_back(get_parameter(param_name));
                }
            }
            
            _get_response_writer.write(response);
        }
    }

    void handle_list_requests()
    {
        auto samples = _list_request_reader.take();
        for (const auto& sample : samples) {
            if (!sample.info().valid()) continue;
            
            // CFT already filtered by node_id
            const auto& request = sample.data();
            
            example_types::ListParametersResponse response;
            response.node_id(_node_name);
            response.request_id(request.request_id());
            
            if (request.prefixes().size() == 0) {
                auto names = list_parameter_names("", request.depth());
                for (const auto& n : names) {
                    response.names().push_back(n);
                }
            } else {
                for (const auto& prefix : request.prefixes()) {
                    auto names = list_parameter_names(std::string(prefix), request.depth());
                    for (const auto& n : names) {
                        response.names().push_back(n);
                    }
                }
            }
            
            _list_response_writer.write(response);
        }
    }

    example_types::SetParametersResponse default_set_handler(
        const example_types::SetParametersRequest& request)
    {
        example_types::SetParametersResponse response;
        response.node_id(_node_name);
        response.request_id(request.request_id());
        
        for (const auto& param : request.parameters()) {
            set_parameter(param);
            
            example_types::SetParameterResult result;
            result.successful(true);
            result.reason("");
            response.results().push_back(result);
        }
        
        publish_event();
        return response;
    }

private:
    std::shared_ptr<DDSParticipantSetup> _participant_setup;
    std::string _node_name;
    std::string _qos_profile;
    SetParametersCallback _server_callback;

    // Parameter storage
    std::map<std::string, example_types::Parameter> _parameters;
    std::vector<example_types::Parameter> _pending_new;
    std::vector<example_types::Parameter> _pending_changed;
    std::vector<example_types::Parameter> _pending_deleted;

    // Topics
    dds::topic::Topic<example_types::ParameterEvent> _event_topic = dds::core::null;
    dds::topic::Topic<example_types::SetParametersRequest> _set_request_topic = dds::core::null;
    dds::topic::Topic<example_types::SetParametersResponse> _set_response_topic = dds::core::null;
    dds::topic::Topic<example_types::GetParametersRequest> _get_request_topic = dds::core::null;
    dds::topic::Topic<example_types::GetParametersResponse> _get_response_topic = dds::core::null;
    dds::topic::Topic<example_types::ListParametersRequest> _list_request_topic = dds::core::null;
    dds::topic::Topic<example_types::ListParametersResponse> _list_response_topic = dds::core::null;

    // Content Filtered Topics (filter requests by node_id)
    dds::topic::ContentFilteredTopic<example_types::SetParametersRequest> _set_request_cft = dds::core::null;
    dds::topic::ContentFilteredTopic<example_types::GetParametersRequest> _get_request_cft = dds::core::null;
    dds::topic::ContentFilteredTopic<example_types::ListParametersRequest> _list_request_cft = dds::core::null;

    // Writers
    dds::pub::DataWriter<example_types::ParameterEvent> _event_writer = dds::core::null;
    dds::pub::DataWriter<example_types::SetParametersResponse> _set_response_writer = dds::core::null;
    dds::pub::DataWriter<example_types::GetParametersResponse> _get_response_writer = dds::core::null;
    dds::pub::DataWriter<example_types::ListParametersResponse> _list_response_writer = dds::core::null;

    // Readers (on CFTs)
    dds::sub::DataReader<example_types::SetParametersRequest> _set_request_reader = dds::core::null;
    dds::sub::DataReader<example_types::GetParametersRequest> _get_request_reader = dds::core::null;
    dds::sub::DataReader<example_types::ListParametersRequest> _list_request_reader = dds::core::null;

    // Read conditions for async handling
    dds::sub::cond::ReadCondition _set_read_condition = dds::core::null;
    dds::sub::cond::ReadCondition _get_read_condition = dds::core::null;
    dds::sub::cond::ReadCondition _list_read_condition = dds::core::null;
};

#endif // DDS_SERVER_PARAMETER_SETUP_HPP
