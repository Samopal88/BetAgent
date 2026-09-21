#!/bin/bash

# BETAGENT — Shadow Research Runner
# This script runs the dual agent shadow runner for research purposes
# It's meant to be scheduled separately from the main pipeline

echo "Starting shadow research run at $(date)"

# Run for football in plus mode
python3 dual_agent_shadow_runner_v1.py --sport football --limit 20 --mode plus
echo "Completed football plus mode"

# Run for hockey in safe mode
python3 dual_agent_shadow_runner_v1.py --sport hockey --limit 20 --mode safe
echo "Completed hockey safe mode"

echo "Shadow research run completed at $(date)"
