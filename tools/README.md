# Tools

This directory contains utility tools for RTI Connext DDS development and debugging.

## rtispy.py

### Quick Start

1. **Get an RTI license and set the environment variable:**
   
   Visit https://www.rti.com/get-connext to request a free trial license (you'll receive it via email within minutes):
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

2. **Run the script** (it will automatically install all requirements):
   ```bash
   ./run_rtispy.sh --domain 1
   ```

That's it! The run script will automatically set up the virtual environment and install all dependencies on first use.

---

### Dependencies:
- RTI Python API
- Textual

#### Connext Python API
- [RTI Connext Python API modules](https://community.rti.com/static/documentation/connext-dds/current/doc/manuals/connext_dds_professional/installation_guide/installing.html#installing-python-c-or-ada-packages)

#### Textual
```bash
pip install textual textual-dev
```

---

### Detailed Setup

#### Getting an RTI License

If you don't have an RTI Connext license:

1. Visit https://www.rti.com/get-connext
2. Fill out the form to request a free trial license
3. You'll receive an automated email with the license file (`rti_license.dat`) within a few minutes
4. Set the `RTI_LICENSE_FILE` environment variable to point to the license file:
   ```bash
   export RTI_LICENSE_FILE=/path/to/downloaded/rti_license.dat
   ```

> **Tip**: Add the `export RTI_LICENSE_FILE=...` line to your `~/.bashrc` or `~/.bash_profile` to make it permanent.

#### Automated Installation (Recommended)

Run the provided installation script which will create a virtual environment and install all dependencies:

```bash
cd tools
./install.sh
```

The script will:
- Create a virtual environment in `tools/rtispy_env/`
- Install RTI Connext Python API (version 7.3.0)
- Install Textual UI framework
- Verify all installations

#### Manual Installation

1. **Create and activate a Python virtual environment:**
```bash
python3 -m venv rtispy_env
source rtispy_env/bin/activate
```

2. **Set up RTI Connext environment:**
```bash
source <path_to_connext>/resource/scripts/rtisetenv_<architecture>.bash
```

3. **Install dependencies:**
```bash
pip install rti.connext==7.3.0
pip install textual textual-dev
```

### Overview
Example tool to deploy onto systems for use in integration debugging without a license  
as it uses the Python libraries.

Implements a terminal based UI navigation to allow for headless/ssh use cases.

### Usage:

#### Using the Run Script (Recommended)
```bash
./run_rtispy.sh --domain 1
```

#### Manual Execution
```bash
source rtispy_env/bin/activate
source <path_to_connext>/resource/scripts/rtisetenv_<architecture>.bash
python rtispy.py --domain 1
```

#### Command-line Options
- `--domain` or `-d`: Specify the DDS domain ID (default: 1)
- `--interval` or `-i`: Set the refresh interval in seconds (default: 10)

#### Example
```bash
./run_rtispy.sh --domain 5 --interval 5
```
