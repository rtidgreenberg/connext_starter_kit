---
mode: agent
description: "Wrapper Classes framework setup"
---

# Wrapper Classes Framework Setup

You have selected the **Wrapper Classes** framework for your DDS application.

## Instructions

1. **Confirm the setup** by running this command in the terminal:
   ```bash
   echo ""
   echo "============================================"
   echo "  Wrapper Classes Framework - Confirmed"
   echo "============================================"
   echo ""
   echo "  Framework:  Wrapper Classes (C++ API)"
   echo "  Reference:  apps/cxx11/example_io_app/"
   echo "  Build:      CMake (top-level)"
   echo ""
   echo "  This framework uses:"
   echo "    - DDSParticipantSetup"
   echo "    - DDSReaderSetup"
   echo "    - DDSWriterSetup"
   echo "    - Distributed Logger integration"
   echo ""
   echo "  Ready to scaffold your application."
   echo "============================================"
   ```

2. **After running the confirmation**, tell the user:
   - The Wrapper Classes framework has been selected
   - Their application will use the `example_io_app` as the reference template
   - Next step: provide a name and description for their new DDS application
   - The build prompt at `.github/prompts/build_cxx.prompt.md` contains the coding standards to follow

3. **Ask the user** for their application name and a brief description of what it should do.
