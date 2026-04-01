#!/bin/bash
# Build the paper. Prints errors and exits non-zero on failure.
output=$(make 2>&1) && echo "Build OK" || { echo "$output"; exit 1; }
# Check for undefined citations in the preserved log
if grep -q "Citation.*undefined" main.log; then
    echo "Warning: undefined citations:"
    grep "Citation.*undefined" main.log | sed 's/.*Citation `\([^'\'']*\)'\''.*/  \1/' | sort -u
    exit 1
fi
