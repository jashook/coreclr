#!/usr/bin/env python3
#
## Licensed to the .NET Foundation under one or more agreements.
## The .NET Foundation licenses this file to you under the MIT license.
## See the LICENSE file in the project root for more information.
#
##
# Title               : performance.py
#
# Notes:
#  
# Script to handle running and collecting performance data for the CoreCLR
# repository. Please note that these measurements are specific and tuned for the
# runtime and jit.
#
################################################################################
################################################################################

import argparse
import asyncio
import datetime
import json
import math
import multiprocessing
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import re
import string
import time
import urllib
import urllib.request
import zipfile

import xml.etree.ElementTree

from collections import defaultdict
from sys import platform as _platform

from coreclr_arguments import *
from async_subprocess_helper import *

################################################################################
# Argument Parser
################################################################################

description = ("""Script to handle running and collecting performance data for the CoreCLR
repository. Please note that these measurements are specific and tuned for the
runtime and jit.""")

parser = argparse.ArgumentParser(description=description)

parser.add_argument("-arch", dest="arch", nargs='?', default="x64", help="Arch, default is x64") 
parser.add_argument("-build_type", dest="build_type", nargs='?', default="Checked", help="Build type, Checked is default")

################################################################################
# Classes
################################################################################

class ChangeDir:
    def __init__(self, dir):
        self.dir = dir
        self.cwd = None

    def __enter__(self):
        self.cwd = os.getcwd()
        os.chdir(self.dir)

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.chdir(self.cwd)

################################################################################
# Helper methods
################################################################################

def filter_exclusions(issues_targets_file, coreclr_args):
    """ Filter the exclusions based on the issues.targets file
    """

    if not os.path.isfile(issues_targets_file):
        raise Exception("A valid issues.targets file is required.")

    contents = None
    with open(issues_targets_file) as file_handle:
        contents = file_handle.read()

    excludes = defaultdict(lambda: None)

    split = contents.split("<ItemGroup")

    def add_expand_path(path):
        if ("**" in path):
            pass
        else:
            if path[0] == "/" if coreclr_args.host_os != "Windows_NT" else "\\":
                path = path[1:]
            path = os.path.join(coreclr_args.test_location, path)
            path = path.replace("*", "")

            if not os.path.isdir(path):
                return

            items = os.listdir(path)
            for item in items:
                item = os.path.join(path, item)
                excludes[item] = ""

    def add_paths(item):
        group = os.pathsep.join(item.split("</ItemGroup>")[0].split(os.linesep)[1:])
        exclude_group = group.split("Include=\"$(XunitTestBinBase)")[1:]

        for new_item in exclude_group:
            path = new_item.split("\">")[0]
            add_expand_path(path)

    for item in split[1:]:
        condition = item.split("Condition=")[1].split(">")[0]

        if "'$(BuildArch)' == 'x64' and '$(TargetsWindows)' != 'true'" in condition and coreclr_args.host_os != "Windows_NT" and coreclr_args.arch == "x64":
            add_paths(item)
        if '$(TargetsWindows)' != 'true' in condition and coreclr_args.host_os != "Windows_NT":
            add_paths(item)
        if "'$(BuildArch)' == 'arm'" in condition and "'$(TargetsWindows)' == 'true'" in condition and coreclr_args.arch == "arm" and coreclr_args.host_os == "Windows_NT":
            add_paths(item)
        if "'$(BuildArch)' == 'arm'" in condition and coreclr_args.arch == "arm":
            add_paths(item)
        if "'$(BuildArch)' == 'arm64'" in condition and "'$(TargetsWindows)' == 'true'" in condition and coreclr_args.arch == "arm64" and coreclr_args.host_os == "Windows_NT":
            add_paths(item)
        if "'$(BuildArch)' == 'arm64'" in condition and coreclr_args.arch == "arm64":
            add_paths(item)
        if "'$(BuildArch)' == 'x64' and '$(TargetsWindows)' == 'true'" in condition and coreclr_args.arch == "x64" and coreclr_args.host_os == "Windows_NT":
            add_paths(item)
        if "'$(BuildArch)' == 'x86' and '$(TargetsWindows)' == 'true'" in condition and coreclr_args.arch == "x86" and coreclr_args.host_os == "Windows_NT":
            add_paths(item)
        if "'$(BuildArch)' == 'arm64' and '$(TargetsWindows)' != 'true'" in condition and coreclr_args.host_os != "Windows_NT" and coreclr_args.arch == "arm64":
            add_paths(item)
        if "'$(BuildArch)' == 'arm' and '$(TargetsWindows)' != 'true'" in condition and coreclr_args.host_os != "Windows_NT" and coreclr_args.arch == "arm":
            add_paths(item)
        if "'$(BuildArch)' != 'x86' or '$(TargetsWindows)' != 'true'" in condition and coreclr_args.host_os != "Windows_NT" and coreclr_args.arch != "x86":
            add_paths(item)

        add_expand_path("JIT/superpmi/superpmicollect/*")

    return excludes

def get_tests(test_location, test_list=None):
    """ Get all of the tests under the test location passed.
    """

    extension = ".sh" if "win32" not in sys.platform else ".cmd"

    if test_list is None:
        test_list = []

    for item in os.listdir(test_location):
        location = os.path.join(test_location, item)
        if os.path.isdir(location):
            get_tests(location, test_list)

        elif extension in item and os.path.basename(test_location) == item.replace(extension, ""):
            test_list.append(location)
    
    return test_list

async def run_test(print_prefix, command, test_results, configuration=None):
    """ Run an individual test
    """
    start = time.perf_counter()
    proc = await asyncio.create_subprocess_shell(" ".join(command),
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
                                                
    stdout, stderr = await proc.communicate()

    elapsed_time = time.perf_counter() - start
    print("{}({:.2f}s) - {}".format(print_prefix, elapsed_time, " ".join(command)))

    return_code = proc.returncode
    decoded_stdout = stdout.decode("ascii")

    if return_code != 0:
        print(decoded_stdout)

    test_result = defaultdict(lambda: None)

    test_result["test_name"] = command[-1]
    test_result["passed"] = return_code != 0
    test_result["output"] = decoded_stdout
    test_result["run_time"] = elapsed_time

    test_results[command[-1]] = test_result

def run_tests(tests, configuration=None):
    """ Run the tests
    """

    test_results = defaultdict(lambda: None)

    async_helper = AsyncSubprocessHelper(tests, 
                                         subproc_count=multiprocessing.cpu_count(), 
                                         verbose=True)
    async_helper.run_to_completion(run_test, test_results, configuration)

################################################################################
# main
################################################################################

def main(args):
    """ Main method
    """

    # await/async requires python >= 3.5
    if sys.version_info.major < 3 and sys.version_info.minor < 5:
        print("Error, language features require the latest python version.")
        print("Please install python 3.7 or greater")

        return 1

    print("CoreCLR Performance.")
    print("-------------------------------------------------------------------")
    
    coreclr_args = CoreclrArguments(args, 
                                    require_built_core_root=True, 
                                    require_built_product_dir=False, 
                                    require_built_test_dir=False, 
                                    default_build_type="Checked")

    tests = get_tests(coreclr_args.test_location)
    exclusions = filter_exclusions(os.path.join(coreclr_args.coreclr_repo_location, "tests", "issues.targets"), coreclr_args)
    
    filtered_tests = []

    for item in tests:
        if not item in exclusions:
            filtered_tests.append(item)

    tests = filtered_tests

    commands = []

    corerun = "corerun"
    pre_command = "bash"

    if "win32" in sys.platform:
        corerun = "corerun.exe"
        pre_command = ""

    for item in tests:
        if pre_command != "":
            commands.append([pre_command, item])
        else:
            commands.append([item])

    print("export CORE_ROOT={}".format(coreclr_args.core_root))
    os.environ["CORE_ROOT"] = os.path.join(coreclr_args.core_root)

    print("Will run over {} tests.".format(len(tests)))
    print("")

    # Run tests without configuration
    run_tests(commands)

################################################################################
# __main__
################################################################################

if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(main(args))
