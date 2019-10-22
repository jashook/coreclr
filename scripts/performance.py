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
import pymongo
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

parser.add_argument("--subproc_count", dest="subproc_count", default=(multiprocessing.cpu_count() / 2) + 1, help="Change if running correctness testing.")

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

async def run_individual_test(print_prefix, command, env, git_hash_value):
    """ Run an individual test
    """
    timeout = 60 * 10 # 60 seconds * amount of minutes

    start = time.perf_counter()
    proc = await asyncio.create_subprocess_shell(" ".join(command),
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE,
                                                env=env)

    stdout = None
    stderr = None
    timed_out = False
    decoded_stdout = ""

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)

    except asyncio.TimeoutError:
        proc.terminate()
        timed_out = True

    elapsed_time = time.perf_counter() - start
    return_code = -1

    if not timed_out:
        print("{}({:.2f}s) - {}".format(print_prefix, elapsed_time, " ".join(command)))

        return_code = proc.returncode
        decoded_stdout = stdout.decode("utf-8")

        if return_code != 0:
            print(decoded_stdout)
    else:
        print("{}({:.2f}s) - TIMEOUT - {}".format(print_prefix, elapsed_time, " ".join(command)))

    complus_vars = defaultdict(lambda: "")
    for item in env:
        if "COMPlus" in item:
            complus_vars[item] = env[item]

    test_result = defaultdict(lambda: None)

    test_result["test_name"] = command[-1]
    test_result["passed"] = return_code == 0
    test_result["output"] = decoded_stdout
    test_result["run_time"] = elapsed_time
    test_result["env"] = complus_vars
    test_result["date"] = datetime.datetime.now()
    test_result["hash"] = git_hash_value

    return test_result

async def run_test_with_jit_order(print_prefix, command, test_results, git_hash_value):
    """ run_test_with_jit_order

        Notes:
            Run through all of the tests with jit order set in order to
            collect information on when/what methods are jitted.
    """

    env = os.environ.copy()
    env["COMPlus_JitOrder"] = "1"

    # Tiered compilation may give us interleaved jit order information.
    env["COMPlus_TieredCompilation"] = "0"

    test_result = await run_individual_test(print_prefix, command, env, git_hash_value)

    output = test_result["output"]

    first_line = True
    methods = []
    for line in output.split(os.linesep):
        if not "|" in line:
            continue
        
        line_split = line.split("|")
        if len(line_split) == 18 or len(line_split) == 17:
            try:
                if first_line is True:
                    first_line = False
                else:
                    method = defaultdict(lambda: None)
                    method_name = line_split[-1].strip()

                    method["method_token"] = line_split[0].strip()
                    method["annotation"] = line_split[1].strip()
                    method["region"] = line_split[2].strip()
                    method["profile_call_count"] = line_split[3].strip()
                    method["has_eh"] = line_split[4].strip() != ""
                    method["frame_type"] = line_split[5].strip()
                    method["has_loops"] = line_split[6].strip() != ""
                    method["call_count"] = int(line_split[7].strip())
                    method["indirect_call_count"] = int(line_split[8].strip())
                    method["basic_block_count"] = int(line_split[9].strip())
                    method["local_var_count"] = int(line_split[10].strip())

                    next_index = 11
                    is_min_opts = line_split[11].strip() == "MinOpts"
                    if is_min_opts is True:
                        method["min_opts"] = True
                        method["tier"] = 0
                    else:
                        method["min_opts"] = False
                        method["tier"] = 1

                        method["assertion_prop_count"] = line_split[next_index].strip()

                        next_index += 1
                        method["cse_count"] = line_split[next_index].strip()

                    next_index += 1
                    method["register_allocator"] = line_split[next_index].strip()

                    next_index += 1
                    method["il_bytes"] = int(line_split[next_index].strip())

                    next_index += 1
                    method["hot_code_size"] = int(line_split[next_index].strip())

                    next_index += 1
                    method["cold_code_size"] = int(line_split[next_index].strip())

                    methods.append(method)
            except:
                # We will end up here if there is are methods with interleaved 
                # output.

                # Just drop these methods.
                pass

    test_result["methods"] = methods
    test_results[command[-1]] = test_result

async def run_test(print_prefix, command, test_results, git_hash_value):
    """ Run a test with a bunch of different configurations
    """

    env=os.environ

    test_runs = []
    test_result = await run_individual_test(print_prefix, command, env, git_hash_value)

    def add_test_result(test_result):
        if not test_result["passed"]:
            return
        
        test_runs.append(test_result)

    if "SKIPPING EXECUTION" in test_result["output"]:
        # This test requires being run with TieredCompilation off.
        # This test can only be run in Tier1 which.
        
        # Re-run with TieredCompliation off
        env = os.environ.copy()
        env["COMPlus_TieredCompilation"] = "0"

        test_result = await run_individual_test(print_prefix, command, env, git_hash_value)
        add_test_result(test_result)

    else:
        # We can run this test with multiple different configurations
        
        if "tracing" in test_result["test_name"] or "GC" in test_result["test_name"]:
            add_test_result(test_result)

        elif test_result["run_time"] > 10:
            # We probably do not want to keep running this test.
            add_test_result(test_result)
            
        else:
            for item in range(10):
                # Run for 10 times with TieredCompilation on
                test_result = await run_individual_test(print_prefix, command, env, git_hash_value)
                add_test_result(test_result)

                # Stop running flakey tests
                if not test_result["passed"]:
                    break

            if test_result["passed"]:
                # If the test failed do not rerun. It is not interesting because we
                # lost data.

                # Re-run with MinOpts (This is Tier0 code only.)
                env = os.environ.copy()
                env["COMPlus_JitMinOpts"] = "1"

                for item in range(10):
                    # Run for 10 times with JitMinOpts on
                    test_result = await run_individual_test(print_prefix, command, env, git_hash_value)
                    add_test_result(test_result)

                    # Stop running flakey tests
                    if not test_result["passed"]:
                        break

                # Re-run with TieredCompilation off (This is Tier1 code only.)
                env = os.environ.copy()
                env["COMPlus_TieredCompilation"] = "0"

                for item in range(10):
                    # Run for 10 times with TieredCompiltion off
                    test_result = await run_individual_test(print_prefix, command, env, git_hash_value)
                    add_test_result(test_result)

                    # Stop running flakey tests
                    if not test_result["passed"]:
                        break

                # Run test AOT
                # env = os.environ.copy()
                # env["COMPlus_TieredCompilation"] = "0"

                # for item in range(10):
                #     # Run for 10 times with TieredCompiltion off
                #     test_result = await run_individual_test(print_prefix, command, env, git_hash_value)
                #     add_test_result(test_result)

                #     # Stop running flakey tests
                #     if not test_result["passed"]:
                #         break

    test_results[command[-1]] = test_runs

def run_tests(tests, subproc_count):
    """ Run the tests
    """

    start = time.perf_counter()
    test_results = defaultdict(lambda: None)
    git_hash_value = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()

    async_helper = AsyncSubprocessHelper(tests,
                                         subproc_count=subproc_count, 
                                         verbose=True)
    async_helper.run_to_completion(run_test_with_jit_order, test_results, git_hash_value)

    # Using the information collected with jit order decide which set of tests we will
    # collect performance information on

    async_helper.run_to_completion(run_test_with_jit_order, test_results, git_hash_value)

    elapsed_time = time.perf_counter() - start

    passed_tests = []
    failed_tests = []

    for item in test_results:
        item = test_results[item]

        test_runs = [expanded_item for expanded_item in item]

        for test_run in test_runs:
            if not test_run["passed"]:
                failed_tests.append(test_run)
            else:
                passed_tests.append(test_run)

    print("")
    print("-------------------------------------------------------------------")
    print("Test run completed {:.2f}s".format(elapsed_time))
    print("")
    print("Total tests run: {}".format(len(passed_tests) + len(failed_tests)))
    print("")
    print("Passed: {}".format(len(passed_tests)))
    print("Failed: {}".format(len(failed_tests)))

    return passed_tests, failed_tests

def upload_results(test_results):
    """ Upload a set of test results to a database.
    """

    ip = "10.158.81.6"

    client = pymongo.MongoClient("mongodb://10.158.81.6:27017/")
    db = client["coreclr-performance"]
    db.test_results.insert_many(test_results)

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
    passed_tests, failed_tests = run_tests(commands, args.subproc_count)

    upload_results(passed_tests + failed_tests)

################################################################################
# __main__
################################################################################

if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(main(args))
