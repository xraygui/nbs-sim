#!/bin/bash

cd /usr/local/src
pip3 install -e xraygui/nbs_core
pip3 install -e nsls-ii-sst/nbs_sim

tail -f /dev/null