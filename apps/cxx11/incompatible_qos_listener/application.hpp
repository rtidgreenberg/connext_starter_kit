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

#ifndef APPLICATION_HPP
#define APPLICATION_HPP

#include <iostream>
#include <csignal>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <algorithm>
#include <dds/core/ddscore.hpp>
#include "Definitions.hpp"

namespace application {

    // Catch control-C and tell application to shut down
    bool shutdown_requested = false;

    inline void stop_handler(int)
    {
        shutdown_requested = true;
        std::cout << "preparing to shut down..." << std::endl;
    }

    inline void setup_signal_handlers()
    {
        signal(SIGINT, stop_handler);
        signal(SIGTERM, stop_handler);
    }

    enum class ParseReturn {
        ok,
        failure,
        exit
    };

    struct ApplicationArguments {
        ParseReturn parse_result;
        unsigned int domain_id;
        rti::config::Verbosity verbosity;
        std::string qos_file_path;
        std::string policy;      // reliability | durability | deadline | ownership
        std::string mode;        // both | subscriber | publisher
        std::string topic_name;
        double timeout_sec;

        ApplicationArguments(
            ParseReturn parse_result_param,
            unsigned int domain_id_param,
            rti::config::Verbosity verbosity_param,
            const std::string& qos_file_path_param,
            const std::string& policy_param,
            const std::string& mode_param,
            const std::string& topic_name_param,
            double timeout_sec_param)
            : parse_result(parse_result_param),
            domain_id(domain_id_param),
            verbosity(verbosity_param),
            qos_file_path(qos_file_path_param),
            policy(policy_param),
            mode(mode_param),
            topic_name(topic_name_param),
            timeout_sec(timeout_sec_param) {}
    };

    inline bool is_one_of(
        const std::string& value,
        const std::vector<std::string>& allowed)
    {
        return std::find(allowed.begin(), allowed.end(), value) != allowed.end();
    }

    inline void set_verbosity(
        rti::config::Verbosity& verbosity,
        int verbosity_value)
    {
        std::cout << "Setting verbosity to value: ";
        switch (verbosity_value) {
            case 0:
            verbosity = rti::config::Verbosity::SILENT;
            std::cout << "0-SILENT" << std::endl;
            break;
            case 1:
            verbosity = rti::config::Verbosity::EXCEPTION;
            std::cout << "1-EXCEPTION" << std::endl;
            break;
            case 2:
            verbosity = rti::config::Verbosity::WARNING;
            std::cout << "2-WARNING" << std::endl;
            break;
            case 3:
            verbosity = rti::config::Verbosity::STATUS_LOCAL;
            std::cout << "3-STATUS_LOCAL" << std::endl;
            break;
            case 4:
            verbosity = rti::config::Verbosity::STATUS_REMOTE;
            std::cout << "4-STATUS_REMOTE" << std::endl;
            break;
            case 5:
            verbosity = rti::config::Verbosity::STATUS_ALL;
            std::cout << "5-STATUS_ALL" << std::endl;
            break;
            default:
            verbosity = rti::config::Verbosity::EXCEPTION;
            break;
        }
    }

    // Parses application arguments for example.
    inline ApplicationArguments parse_arguments(int argc, char *argv[])
    {
        int arg_processing = 1;
        bool show_usage = false;
        ParseReturn parse_result = ParseReturn::ok;
        unsigned int domain_id = domains::DEFAULT_DOMAIN_ID;
        rti::config::Verbosity verbosity(rti::config::Verbosity::EXCEPTION);
        std::string qos_file_path = "dds/qos/DDS_QOS_PROFILES.xml"; // Default QoS file
        std::string policy = "reliability";
        std::string mode = "both";
        std::string topic_name = topics::POSITION_TOPIC;
        double timeout_sec = 10.0;

        while (arg_processing < argc) {
            if ((argc > arg_processing + 1) 
            && (strcmp(argv[arg_processing], "-d") == 0
            || strcmp(argv[arg_processing], "--domain") == 0)) {
                domain_id = atoi(argv[arg_processing + 1]);
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-v") == 0
            || strcmp(argv[arg_processing], "--verbosity") == 0)) {
                set_verbosity(verbosity, atoi(argv[arg_processing + 1]));
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-q") == 0
            || strcmp(argv[arg_processing], "--qos-file") == 0)) {
                qos_file_path = argv[arg_processing + 1];
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-p") == 0
            || strcmp(argv[arg_processing], "--policy") == 0)) {
                policy = argv[arg_processing + 1];
                if (!is_one_of(policy,
                        {"reliability", "durability", "deadline", "ownership"})) {
                    std::cout << "Bad --policy value: " << policy << std::endl;
                    show_usage = true;
                    parse_result = ParseReturn::failure;
                    break;
                }
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-m") == 0
            || strcmp(argv[arg_processing], "--mode") == 0)) {
                mode = argv[arg_processing + 1];
                if (!is_one_of(mode, {"both", "subscriber", "publisher"})) {
                    std::cout << "Bad --mode value: " << mode << std::endl;
                    show_usage = true;
                    parse_result = ParseReturn::failure;
                    break;
                }
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "-t") == 0
            || strcmp(argv[arg_processing], "--topic") == 0)) {
                topic_name = argv[arg_processing + 1];
                arg_processing += 2;
            } else if ((argc > arg_processing + 1)
            && (strcmp(argv[arg_processing], "--timeout") == 0)) {
                timeout_sec = atof(argv[arg_processing + 1]);
                arg_processing += 2;
            } else if ((strcmp(argv[arg_processing], "-h") == 0
            || strcmp(argv[arg_processing], "--help") == 0)) {
                std::cout << "Incompatible QoS Listener - on_requested_incompatible_qos at the DomainParticipant level." << std::endl;
                show_usage = true;
                parse_result = ParseReturn::exit;
                break;
            } else {
                std::cout << "Bad parameter." << std::endl;
                show_usage = true;
                parse_result = ParseReturn::failure;
                break;
            }
        }
        if (show_usage) {
            std::cout << "Usage:\n"\
            "    -d, --domain       <int>   Domain ID this application will\n" \
            "                               run on.  \n"
            "                               Default: 1\n"\
            "    -v, --verbosity    <int>   How much debugging output to show.\n"\
            "                               Range: 0-5 \n"
            "                               Default: 1\n"
            "    -q, --qos-file     <str>   Path to QoS profile XML file.\n"\
            "                               Default: dds/qos/DDS_QOS_PROFILES.xml\n"\
            "    -p, --policy       <str>   QoS policy to make incompatible.\n"\
            "                               reliability|durability|deadline|ownership\n"\
            "                               Default: reliability\n"\
            "    -m, --mode         <str>   both|subscriber|publisher\n"\
            "                               Default: both\n"\
            "    -t, --topic        <str>   Topic name.\n"\
            "                               Default: Position\n"\
            "        --timeout      <num>   Seconds to wait for the callback.\n"\
            "                               Default: 10"
            << std::endl;
        }

        return ApplicationArguments(
            parse_result, domain_id, verbosity, qos_file_path,
            policy, mode, topic_name, timeout_sec);
    }

}  // namespace application

#endif  // APPLICATION_HPP
