#!/bin/bash
cd "$(dirname "$0")"
chmod +x diagnose_entry_a.sh repair_lmstudio_35b_path.sh
./diagnose_entry_a.sh
read -r -p "Press Enter to close..."
