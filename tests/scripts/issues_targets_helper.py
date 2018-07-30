#!/usr/bin/env python
#
## Licensed to the .NET Foundation under one or more agreements.
## The .NET Foundation licenses this file to you under the MIT license.
## See the LICENSE file in the project root for more information.
#
##
# Title               :issues_targets_helper.py
#
# Script to help working with issues.targets
#
################################################################################

import argparse
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import re
import string

import xml.etree.ElementTree

from collections import defaultdict
from sys import platform as _platform

################################################################################
# Argument Parser
################################################################################

description = ("""Script to help working with issues.targets. Specifically it
                  allows adding tests for a specific os/arch. It will also
                  de-dup and sort the exclusion list.""")

# Use either - or / to designate switches.
parser = argparse.ArgumentParser(description=description, prefix_chars='-/')

parser.add_argument("-arch", dest="arch", nargs='?', default="x64")
parser.add_argument("-core_root", dest="core_root", nargs='?', default=None)
parser.add_argument("-coreclr_repo_location", dest="coreclr_repo_location", default=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

################################################################################
# Classes
################################################################################

class ExcludeList:
    def __init__(self, exclude_list_location):
        assert os.path.isfile(exclude_list_location)
        self.exclude_list_location = exclude_list_location

        project = xml.etree.ElementTree.parse(exclude_list_location).getroot()

        self.exclude_list = defaultdict(lambda: None)
        
        for exclude_list_element in project:
            conditions = exclude_list_element.attrib['Condition']

            arch = "any"
            host_os = "any"

            conditions = conditions.split("and")
            for condition in conditions:
                if "$(BuildArch)" in condition:
                    arch = condition.split("==")[1]
                    arch = re.sub("[" + string.punctuation + "]", "", arch)

                if "$(TargetsWindows)" in condition:
                    host_os = "windows" if "==" in condition else "unix"

            self.exclude_list[host_os] = defaultdict(lambda: None)
            self.exclude_list[host_os][arch] = defaultdict(lambda: None)

            exclude_list = []
            for exclude_element in exclude_list_element:
                issue = exclude_element[0].text
                self.exclude_list[host_os][arch][exclude_element.attrib["Include"]] = issue

################################################################################
# Main
################################################################################

def main(args):
    issues_targets_location = os.path.join(args.coreclr_repo_location, "tests", "issues.targets")

    exclude_list = ExcludeList(issues_targets_location)
    pass

################################################################################
# __main__
################################################################################

if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(main(args))