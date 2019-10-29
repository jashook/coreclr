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
import cpuinfo
import datetime
import json
import math
import multiprocessing
import os
import platform
import psutil
import pymongo
import pyodbc
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

from async_subprocess_helper import *
from coreclr_arguments import *
from sql_helper import *

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

        if condition == '"\'$(XunitTestBinBase)\' != \'\'"':
            add_paths(item)
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

async def run_individual_test(print_prefix, command, env, git_hash_value, git_date_time):
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

        try:
            decoded_stdout = stdout.decode("utf-8")
        except:
            decoded_stdout = ""

        if return_code != 0:
            print(decoded_stdout)
    else:
        print("{}({:.2f}s) - TIMEOUT - {}".format(print_prefix, elapsed_time, " ".join(command)))

    complus_vars = defaultdict(lambda: "")
    for item in env:
        if "COMPlus" in item:
            complus_vars[item] = env[item]

    test_result = defaultdict(lambda: None)

    sep_character = os.sep
    if sep_character == "\\":
        sep_character = "\\{}".format(os.sep)

    test_name = re.split("\w+\.\w+\.\w+{}".format(sep_character), command[-1])[1]

    test_result["test_name"] = test_name
    test_result["passed"] = return_code == 0
    test_result["output"] = decoded_stdout
    test_result["run_time"] = elapsed_time
    test_result["env"] = complus_vars
    test_result["date"] = git_date_time
    test_result["hash"] = git_hash_value

    return test_result

async def run_test_with_jit_order(print_prefix, command, test_results, git_hash_value, git_date_time):
    """ run_test_with_jit_order

        Notes:
            Run through all of the tests with jit order set in order to
            collect information on when/what methods are jitted.
    """

    env = os.environ.copy()
    env["COMPlus_JitOrder"] = "1"

    test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)

    output = test_result["output"]
    jit_order_output_removed = []

    first_line = True
    methods = []
    for line in output.split(os.linesep):
        if "---------+" in line or "|  Profiled  |" in line:
            continue

        if not "|" in line:
            jit_order_output_removed.append(line)
            continue
        
        line_split = line.split("|")
        if len(line_split) == 18 or len(line_split) == 17:
            try:
                if first_line is True:
                    first_line = False
                else:
                    method = defaultdict(lambda: None)
                    method_name = line_split[-1].strip()

                    assert method_name !=  None

                    method["method_id"] = line_split[0].strip()
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
                    method["method_name"] = method_name

                    next_index = 11
                    is_min_opts = line_split[11].strip() == "MinOpts"
                    if is_min_opts is True:
                        method["min_opts"] = True
                        method["tier"] = 0
                    else:
                        method["min_opts"] = False
                        method["tier"] = 1

                        method["assertion_prop_count"] = int(line_split[next_index].strip())

                        next_index += 1
                        method["cse_count"] = int(line_split[next_index].strip())

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

    jit_order_output_removed = os.linesep.join(jit_order_output_removed)
    test_result["output"] = jit_order_output_removed

    if len(test_result) > 2048:
        print("Shortening output to store later.")
        test_result["output"] = test_result[:2048]

    test_result["methods"] = methods
    test_results[command[-1]] = test_result

async def run_test(print_prefix, command, test_results, git_hash_value, git_date_time):
    """ Run a test with a bunch of different configurations
    """

    env=os.environ

    test_runs = []
    test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)

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

        test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)
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
                test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)
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
                    test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)
                    add_test_result(test_result)

                    # Stop running flakey tests
                    if not test_result["passed"]:
                        break

                # Re-run with TieredCompilation off (This is Tier1 code only.)
                env = os.environ.copy()
                env["COMPlus_TieredCompilation"] = "0"

                for item in range(10):
                    # Run for 10 times with TieredCompiltion off
                    test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)
                    add_test_result(test_result)

                    # Stop running flakey tests
                    if not test_result["passed"]:
                        break

                # Run test AOT
                # env = os.environ.copy()
                # env["COMPlus_TieredCompilation"] = "0"

                # for item in range(10):
                #     # Run for 10 times with TieredCompiltion off
                #     test_result = await run_individual_test(print_prefix, command, env, git_hash_value, git_date_time)
                #     add_test_result(test_result)

                #     # Stop running flakey tests
                #     if not test_result["passed"]:
                #         break

    test_results[command[-1]] = test_runs

def run_tests(tests, coreclr_args, subproc_count):
    """ Run the tests
    """

    start = time.perf_counter()
    test_results = defaultdict(lambda: None)
    git_hash_value = subprocess.check_output(["git", "rev-parse", "HEAD"]).decode("utf-8").strip()
    git_date_time = subprocess.check_output(["git", "show", "-s", "--format=%ci", git_hash_value]).decode("utf-8").strip()

    # Remove timezone
    git_date_time = git_date_time.split(" -")[0]
    git_date_time = datetime.datetime.strptime(git_date_time, "%Y-%m-%d %H:%M:%S")

    async_helper = AsyncSubprocessHelper(tests,
                                         subproc_count=subproc_count * 2, 
                                         verbose=True)
    async_helper.run_to_completion(run_test_with_jit_order, test_results, git_hash_value, git_date_time)

    # Using the information collected with jit order decide which set of tests we will
    # collect performance information on

    elapsed_time = time.perf_counter() - start

    passed_tests = []
    failed_tests = []

    for item in test_results:
        item = test_results[item]

        if not item["passed"]:
            failed_tests.append(item)
        else:
            passed_tests.append(item)

    print("")
    print("-------------------------------------------------------------------")
    print("Test run completed {:.2f}s".format(elapsed_time))
    print("")
    print("Total tests run: {}".format(len(passed_tests) + len(failed_tests)))
    print("")
    print("Passed: {}".format(len(passed_tests)))
    print("Failed: {}".format(len(failed_tests)))
 
    start = time.perf_counter()
    upload_results(passed_tests + failed_tests, coreclr_args, git_hash_value, git_date_time, verbose=False)
    elapsed_time = time.perf_counter() - start

    print("Finished uploading ({}s)".format(elapsed_time))

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

def upload_results(test_results, coreclr_args, git_commit, git_commit_date, verbose=True):
    """ Upload a set of test results to a database.
    """

    server = "coreclr-performance.database.windows.net"
    database = "coreclr-performance" 
    username = "robox"
    password = os.environ["robox-pw"]

    if password == "":
        print("Unable to upload data, robox-pw is unset.")
        return

    connection = None

    try:
        connection = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};SERVER='+server+';DATABASE='+database+';UID='+username+';PWD='+ password)
    except:
        print("Failed to connect please verify the driver is installed.")
        print("https://docs.microsoft.com/en-us/sql/connect/odbc/windows/system-requirements-installation-and-driver-files?view=sql-server-ver15#installing-microsoft-odbc-driver-for-sql-server")

        return

    cursor = connection.cursor()

    def execute_command(command):
        if verbose is True:
            print(command)

        cursor.execute(command)

        ret_val = None
        if not "INSERT" in command:
            ret_val = cursor.fetchone()

        cursor.commit()
        return ret_val

    hostname = platform.node()
    cpu = cpuinfo.get_cpu_info()

    processor = cpu['brand']
    arch = cpu["raw_arch_string"]
    host_os = coreclr_args.host_os

    test_arch = coreclr_args.arch

    mem = psutil.virtual_memory()
    memory = int(mem.total / (1024 * 1024 * 1024))
    command = "EXEC add_test_run @HostName = '{}', @Processor = '{}', @Memory = {}, @HostOs = '{}', @HostArch = '{}', @TestRunArch = '{}', @Commit = '{}', @CommitDate = '{}'".format(hostname,
                                                                                                                                                                                         processor,
                                                                                                                                                                                         memory,
                                                                                                                                                                                         host_os,
                                                                                                                                                                                         arch,
                                                                                                                                                                                         test_arch,
                                                                                                                                                                                         git_commit,
                                                                                                                                                                                         git_commit_date)

    test_run_id = execute_command(command)[0]

    total = len(test_results)
    methods_command = "INSERT methods (method_id, annotation, region, profile_call_count, has_eh, frame_type, has_loops, call_count, indirect_call_count, basic_block_count, local_var_count, min_opts, tier, assertion_prop_count, cse_count, register_allocator, il_bytes, hot_code_size, cold_code_size, method_name, test) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

    # Upload the environment data
    env_data_insert_statement = "INSERT env_data (key_name, env_value, test) VALUES (?, ?, ?)"

    with SqlHelper(cursor, env_data_insert_statement, verbose=verbose) as env_sql_command:
        with SqlHelper(cursor, methods_command, verbose=verbose) as method_sql_command:
            for test_index, item in enumerate(test_results):
                start = time.perf_counter()

                if type(item) == str:
                    item = test_results[item]

                # Insert the high level test data first to get its key
                passed = 1 if item["passed"] is True else 0
                output = item["output"].replace("'", '"')
                command = "EXEC add_test @TestName = '{}', @Passed = {}, @TestOutput = '{}', @RunTime = {}, @GitHash = '{}', @Date = '{}', @TestRunId = '{}'".format(item["test_name"], passed, output, item["run_time"], item["hash"], item["date"], test_run_id)
                result = execute_command(command)

                foreign_key = result[0]

                for env_var in item["env"]:
                    env_sql_command.add_data((env_var, item["env"][env_var], foreign_key))

                if len(item["methods"]) > 0:
                    # Upload all of the methods for a specific test results
                    for method in item["methods"]:
                        value = []
                        has_eh = 1 if method["has_eh"] is True else 0
                        has_loops = 1 if method["has_loops"] is True else 0
                        min_opts = 1 if method["min_opts"] is True else 0

                        
                        value.append(method["method_id"])
                        value.append(method["annotation"])
                        value.append(method["region"])
                        value.append(method["profile_call_count"])
                        value.append(has_eh)
                        value.append(method["frame_type"])
                        value.append(has_loops)
                        value.append(method["call_count"])
                        value.append(method["indirect_call_count"])
                        value.append(method["basic_block_count"])
                        value.append(method["local_var_count"])
                        value.append(min_opts)
                        value.append(method["tier"])

                        if "assertion_prop_count" in method.keys():
                            value.append(method["assertion_prop_count"])
                            value.append(method["cse_count"])
                        else:
                            value.append(-1)
                            value.append(-1)
                        
                        value.append(method["register_allocator"])
                        value.append(method["il_bytes"])
                        value.append(method["hot_code_size"])
                        value.append(method["cold_code_size"])
                        value.append(method["method_name"])
                        value.append(foreign_key)

                        method_sql_command.add_data(value)
                        
                    elapsed_time = time.perf_counter() - start

                    print("[{}:{}] - Uploaded ({:.2f}s)".format(test_index, total, elapsed_time))

    print("Methods: Uploaded ({:.2f}s)".format(elapsed_time))

    cursor.close()
    connection.close()

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
    filtered_tests = []

    # Remove all tracing* and GC* tests
    for item in tests:
        if not "GC" in item and not "tracing" in item:
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
    passed_tests, failed_tests = run_tests(commands, coreclr_args, args.subproc_count)

    upload_results(passed_tests + failed_tests)

################################################################################
# __main__
################################################################################

if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(main(args))
