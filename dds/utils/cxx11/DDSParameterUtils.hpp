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

#ifndef DDS_PARAMETER_UTILS_HPP
#define DDS_PARAMETER_UTILS_HPP

#include <string>
#include <vector>
#include <chrono>
#include <iostream>

#include "ExampleTypes.hpp"

// Optional YAML support - define DDS_PARAMETER_YAML_SUPPORT before including to enable
#ifdef DDS_PARAMETER_YAML_SUPPORT
#include <yaml-cpp/yaml.h>
#endif

/*
 * DDSParameterUtils
 * 
 * Static utility functions for parameter creation, access, and YAML loading.
 * Shared by DDSServerParameterSetup and DDSClientParameterSetup.
 */
namespace DDSParameterUtils {

    //--------------------------------------------------------------------------
    // Parameter Factory Methods
    //--------------------------------------------------------------------------
    
    inline example_types::Parameter make_parameter(const std::string& name, const std::string& value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.string_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name, const char* value)
    {
        return make_parameter(name, std::string(value));
    }

    inline example_types::Parameter make_parameter(const std::string& name, double value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.double_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name, int64_t value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.integer_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name, int value)
    {
        return make_parameter(name, static_cast<int64_t>(value));
    }

    inline example_types::Parameter make_parameter(const std::string& name, bool value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.bool_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name, 
                                                    const std::vector<uint8_t>& value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.byte_array_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name,
                                                    const std::vector<double>& value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.double_array_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name,
                                                    const std::vector<int64_t>& value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.integer_array_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name,
                                                    const std::vector<bool>& value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.bool_array_value(value);
        param.value(pval);
        return param;
    }

    inline example_types::Parameter make_parameter(const std::string& name,
                                                    const std::vector<std::string>& value)
    {
        example_types::Parameter param;
        param.name(name);
        example_types::ParameterValue pval;
        pval.string_array_value(value);
        param.value(pval);
        return param;
    }

    //--------------------------------------------------------------------------
    // Parameter Value Accessors
    //--------------------------------------------------------------------------

    inline std::string get_string(const example_types::Parameter& param)
    {
        return param.value().string_value();
    }

    inline double get_double(const example_types::Parameter& param)
    {
        return param.value().double_value();
    }

    inline int64_t get_integer(const example_types::Parameter& param)
    {
        return param.value().integer_value();
    }

    inline bool get_bool(const example_types::Parameter& param)
    {
        return param.value().bool_value();
    }

    inline example_types::ParameterType get_type(const example_types::Parameter& param)
    {
        return static_cast<example_types::ParameterType>(param.value()._d());
    }

    inline std::string type_to_string(example_types::ParameterType type)
    {
        switch (type) {
            case example_types::ParameterType::PARAMETER_NOT_SET: return "NOT_SET";
            case example_types::ParameterType::PARAMETER_BOOL: return "bool";
            case example_types::ParameterType::PARAMETER_INTEGER: return "integer";
            case example_types::ParameterType::PARAMETER_DOUBLE: return "double";
            case example_types::ParameterType::PARAMETER_STRING: return "string";
            case example_types::ParameterType::PARAMETER_BYTE_ARRAY: return "byte_array";
            case example_types::ParameterType::PARAMETER_BOOL_ARRAY: return "bool_array";
            case example_types::ParameterType::PARAMETER_INTEGER_ARRAY: return "integer_array";
            case example_types::ParameterType::PARAMETER_DOUBLE_ARRAY: return "double_array";
            case example_types::ParameterType::PARAMETER_STRING_ARRAY: return "string_array";
            default: return "unknown";
        }
    }

    inline uint64_t current_timestamp_ns()
    {
        return static_cast<uint64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
    }

#ifdef DDS_PARAMETER_YAML_SUPPORT
    //--------------------------------------------------------------------------
    // YAML Loading (requires yaml-cpp)
    //--------------------------------------------------------------------------

    inline std::vector<example_types::Parameter> load_from_yaml(const std::string& filepath)
    {
        std::vector<example_types::Parameter> params;
        
        try {
            YAML::Node config = YAML::LoadFile(filepath);
            
            if (config["parameters"]) {
                for (const auto& param_node : config["parameters"]) {
                    std::string name = param_node["name"].as<std::string>();
                    std::string type = param_node["type"].as<std::string>();
                    
                    if (type == "string") {
                        params.push_back(make_parameter(name, param_node["value"].as<std::string>()));
                    } else if (type == "double") {
                        params.push_back(make_parameter(name, param_node["value"].as<double>()));
                    } else if (type == "integer") {
                        params.push_back(make_parameter(name, param_node["value"].as<int64_t>()));
                    } else if (type == "bool") {
                        params.push_back(make_parameter(name, param_node["value"].as<bool>()));
                    } else if (type == "string_array") {
                        params.push_back(make_parameter(name, 
                            param_node["value"].as<std::vector<std::string>>()));
                    } else if (type == "double_array") {
                        params.push_back(make_parameter(name,
                            param_node["value"].as<std::vector<double>>()));
                    } else if (type == "integer_array") {
                        params.push_back(make_parameter(name,
                            param_node["value"].as<std::vector<int64_t>>()));
                    } else if (type == "bool_array") {
                        params.push_back(make_parameter(name,
                            param_node["value"].as<std::vector<bool>>()));
                    }
                }
            }
        } catch (const std::exception& e) {
            std::cerr << "[DDSParameterUtils] YAML error: " << e.what() << std::endl;
        }
        
        return params;
    }
#endif

} // namespace DDSParameterUtils

#endif // DDS_PARAMETER_UTILS_HPP
