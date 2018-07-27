#!/usr/bin/env python
################################################################################
################################################################################
#
# Module: runtest.py
#
# Notes:
#  
# Universal script to setup and run the xunit msbuild test runner.
#
# Use the instructions here:
#    https://github.com/dotnet/coreclr/blob/master/Documentation/building/windows-test-instructions.md 
#    https://github.com/dotnet/coreclr/blob/master/Documentation/building/unix-test-instructions.md
#
################################################################################
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

description = ("""Simple script that essentially sets up and runs either runtest.cmd
                  or runtests.sh. This wrapper is necessary to do all the setup work.

                  Note that this is required because there is not a unified test runner
                  for coreclr.""")

# Use either - or / to designate switches.
parser = argparse.ArgumentParser(description=description, prefix_chars='-/')

parser.add_argument("-arch", dest="arch", nargs='?', default="x64")
parser.add_argument("-build_type", dest="build_type", nargs='?', default="Debug")
parser.add_argument("-test_location", dest="test_location", nargs="?", default=None)
parser.add_argument("-core_root", dest="core_root", nargs='?', default=None)
parser.add_argument("-coreclr_repo_location", dest="coreclr_repo_location", default=os.getcwd())
parser.add_argument("--analyze_results_only", dest="analyze_results_only", action="store_true", default=False)
parser.add_argument("--verbose", dest="verbose", action="store_true", default=False)

# Only used on Unix
parser.add_argument("-test_native_bin_location", dest="test_native_bin_location", nargs='?', default=None)

################################################################################
# Globals
################################################################################

g_verbose = False
file_name_cache = defaultdict(lambda: None)

################################################################################
# Classes
################################################################################

class DebugEnv:
    def __init__(self, 
                 host_os, 
                 arch, 
                 build_type, 
                 env, 
                 core_root,
                 coreclr_repo_location, 
                 test):
        """ Go through the failing tests and create repros for them

        Args:
            host_os (String)        : os
            arch (String)           : architecture
            build_type (String)     : build configuration (debug, checked, release)
            env                     : env for the repro
            core_root (String)      : Core_Root path
            coreclr_repo_location   : coreclr repo location
            test ({})               : The test metadata
        
        """
        self.unique_name = "%s_%s_%s_%s" % (test["name"],
                                            host_os,
                                            arch,
                                            build_type)

        self.host_os = host_os
        self.arch = arch
        self.build_type = build_type
        self.env = env
        self.core_root = core_root
        self.test = test
        self.test_location = test["test_path"]
        self.coreclr_repo_location = coreclr_repo_location

        self.__create_repro_wrapper__()

        self.path = None
        
        if self.host_os == "Windows_NT":
            self.path = self.unique_name + ".cmd"
        else:
            self.path = self.unique_name + ".sh"

        repro_location = os.path.join(coreclr_repo_location, "bin", "repro")
        assert os.path.isdir(repro_location)

        self.path = os.path.join(repro_location, self.path)
        
        exe_location = os.path.splitext(self.test_location)[0] + ".exe"
        if os.path.isfile(exe_location):
            self.exe_location = exe_location
            self.__add_configuration_to_launch_json__()

    def __add_configuration_to_launch_json__(self):
        """ Add to or create a launch.json with debug information for the test

        Notes:
            This will allow debugging using the cpp extension in vscode.
        """

        repro_location = os.path.join(self.coreclr_repo_location, "bin", "repro")
        assert os.path.isdir(repro_location)

        vscode_dir = os.path.join(repro_location, ".vscode")
        if not os.path.isdir(vscode_dir):
            os.mkdir(vscode_dir)

        assert os.path.isdir(vscode_dir)

        launch_json_location = os.path.join(vscode_dir, "launch.json")
        if not os.path.isfile(launch_json_location):
            initial_json = {
                "version": "0.2.0",
                "configurations": []
            }

            json_str = json.dumps(initial_json, 
                                  indent=4, 
                                  separators=(',', ': '))

            with open(launch_json_location, 'w') as file_handle:
                file_handle.write(json_str)

        launch_json = None
        with open(launch_json_location) as file_handle:
            launch_json = file_handle.read()
        
        launch_json = json.loads(launch_json)

        configurations = launch_json["configurations"]

        dbg_type = "cppvsdbg" if self.host_os == "Windows_NT" else ""
        core_run = os.path.join(self.core_root, "corerun")

        env = {
            "COMPlus_AssertOnNYI": "1",
            "COMPlus_ContinueOnAssert": "0"
        }

        if self.env is not None:
            # Convert self.env to a defaultdict
            self.env = defaultdict(lambda: None, self.env)
            for key, value in env.iteritems():
                self.env[key] = value
            
        else:
            self.env = env

        environment = []
        for key, value in self.env.iteritems():
            env = {
                "name": key,
                "value": value
            }

            environment.append(env)

        configuration = defaultdict(lambda: None, {
            "name": self.unique_name,
            "type": dbg_type,
            "request": "launch",
            "program": core_run,
            "args": [self.exe_location],
            "stopAtEntry": False,
            "cwd": os.path.join("${workspaceFolder}", "..", ".."),
            "environment": environment,
            "externalConsole": True
        })

        if self.build_type.lower() != "release":
            symbol_path = os.path.join(self.core_root, "PDB")
            configuration["symbolSearchPath"] = symbol_path

        # Update configuration if it already exists.
        config_exists = False
        for index, config in enumerate(configurations):
            if config["name"] == self.unique_name:
                configurations[index] = configuration
                config_exists = True

        if not config_exists:
            configurations.append(configuration)
        json_str = json.dumps(launch_json,
                              indent=4, 
                              separators=(',', ': '))

        with open(launch_json_location, 'w') as file_handle:
            file_handle.write(json_str)

    def __create_repro_wrapper__(self):
        """ Create the repro wrapper
        """

        if self.host_os == "Windows_NT":
            self.__create_batch_wrapper__()
        else:
            self.__create_bash_wrapper__()

    def __create_batch_wrapper__(self):
        """ Create a windows batch wrapper
        """
    
        wrapper = \
"""@echo off
REM ============================================================================
REM Repro environment for %s
REM 
REM Notes:
REM 
REM This wrapper is automatically generated by runtest.py. It includes the
REM necessary environment to reproduce a failure that occured during running
REM the tests.
REM
REM In order to change how this wrapper is generated, see
REM runtest.py:__create_batch_wrapper__(). Please note that it is possible
REM to recreate this file by running tests/runtest.py --analyze_results_only
REM with the appropriate environment set and the correct arch and build_type
REM passed.
REM
REM ============================================================================

REM Set Core_Root if it has not been already set.
if "%%CORE_ROOT%%"=="" set CORE_ROOT=%s

echo Core_Root is set to: "%%CORE_ROOT%%"

""" % (self.unique_name, self.core_root)

        line_sep = os.linesep

        if self.env is not None:
            for key, value in self.env:
                wrapper += "echo set %s=%s%s" % (key, value, line_sep)
                wrapper += "set %s=%s%s" % (key, value, line_sep)

        wrapper += "%s" % line_sep
        wrapper += "echo call %s%s" % (self.test_location, line_sep) 
        wrapper += "call %s%s" % (self.test_location, line_sep) 

        self.wrapper = wrapper
    
    def __create_bash_wrapper__(self):
        """ Create a unix bash wrapper
        """
    
        wrapper = \
"""
#============================================================================
# Repro environment for %s
# 
# Notes:
#
# This wrapper is automatically generated by runtest.py. It includes the
# necessary environment to reproduce a failure that occured during running
# the tests.
#
# In order to change how this wrapper is generated, see
# runtest.py:__create_batch_wrapper__(). Please note that it is possible
# to recreate this file by running tests/runtest.py --analyze_results_only
# with the appropriate environment set and the correct arch and build_type
# passed.
#
# ============================================================================

# Set Core_Root if it has not been already set.
if [ -z ${CORE_ROOT} ]; then echo "CORE_ROOT is set to $CORE_ROOT"; else export CORE_ROOT=%s; fi

""" % (self.unique_name, self.core_root)

        line_sep = os.linesep

        if self.env is not None:
            for key, value in self.env:
                wrapper += "echo export %s=%s%s" % (key, value, line_sep)
                wrapper += "export %s=%s%s" % (key, value, line_sep)

        wrapper += "%s" % line_sep
        wrapper += "echo bash %s%s" % (self.test_location, line_sep) 
        wrapper += "bash %s%s" % (self.test_location, line_sep) 

        self.wrapper = wrapper

    def write_repro(self):
        """ Write out the wrapper

        Notes:
            This will check if the wrapper repros or not. If it does not repro
            it will be put into an "unstable" folder under bin/repro.
            Else it will just be written out.

        """

        with open(self.path, 'w') as file_handle:
            file_handle.write(self.wrapper)


################################################################################
# Helper Functions
################################################################################
   
def create_and_use_test_env(_os, env, func):
    """ Create a test env based on the env passed

    Args:
        _os(str)                        : OS name
        env(defaultdict(lambda: None))  : complus variables, key,value dict
        func(lambda)                    : lambda to call, after creating the 
                                        : test_env

    Notes:
        Using the env passed, create a temporary file to use as the
        test_env to be passed for runtest.cmd. Note that this only happens
        on windows, until xunit is used on unix there is no managed code run
        in runtest.sh.
    """

    complus_vars = defaultdict(lambda: None)

    for key in env:
        value = env[key]
        if "complus" in key.lower():
            complus_vars[key] = value

    if len(complus_vars.keys()) > 0:
        print "Found COMPlus variables in the current environment"
        print

        file_header = None

        if _os == "Windows_NT":
            file_header = \
"""@echo off
REM Temporary test env for test run.

"""
        else:
            file_header = \
"""# Temporary test env for test run.

"""

        with tempfile.NamedTemporaryFile() as test_env:
            with open(test_env.name, 'w') as file_handle:
                file_handle.write(file_header)
                
                for key in complus_vars:
                    value = complus_vars[key]
                    command = None
                    if _os == "Windows_NT":
                        command = "set"
                    else:
                        command = "export"

                    print "Unset %s" % key
                    os.environ[key] = ""

                    file_handle.write("%s %s=%s%s" % (command, key, value, os.linesep))

            contents = None
            with open(test_env.name) as file_handle:
                contents = file_handle.read()

            print
            print "TestEnv: %s" % test_env.name
            print 
            print "Contents:"
            print
            print contents
            print

            return func(test_env.name)

    else:
        return func(None)

def get_environment():
    """ Get all the COMPlus_* Environment variables
    
    Notes:
        Windows uses msbuild for its test runner. Therefore, all COMPlus
        variables will need to be captured as a test_env script and passed
        to runtest.cmd.
    """

    complus_vars = defaultdict(lambda: "")
    
    for key in os.environ:
        if "complus" in key.lower():
            complus_vars[key] = os.environ[key]
            os.environ[key] = ''
        elif "superpmi" in key.lower():
            complus_vars[key] = os.environ[key]
            os.environ[key] = ''

    return complus_vars

def call_msbuild(coreclr_repo_location,
                 dotnetcli_location,
                 host_os,
                 arch,
                 build_type, 
                 sequential=False):
    """ Call msbuild to run the tests built.

    Args:
        coreclr_repo_location(str)  : path to coreclr repo
        dotnetcli_location(str)     : path to the dotnet cli in the tools dir
        sequential(bool)            : run sequentially if True

        host_os(str)                : os
        arch(str)                   : architecture
        build_type(str)             : configuration

    Notes:
        At this point the environment should be setup correctly, including
        the test_env, should it need to be passed.

    """
    global g_verbose

    common_msbuild_arguments = ["/nologo", "/nodeReuse:false", "/p:Platform=%s" % arch]

    if sequential:
        common_msbuild_arguments += ["/p:ParallelRun=false"]
    else:
        common_msbuild_arguments += ["/maxcpucount"]

    logs_dir = os.path.join(coreclr_repo_location, "bin", "Logs")
    if not os.path.isdir(logs_dir):
        os.makedirs(logs_dir)
    
    command =   [dotnetcli_location,
                 "msbuild",
                 os.path.join(coreclr_repo_location, "tests", "runtest.proj"),
                 "/p:Runtests=true",
                 "/clp:showcommandline"]

    log_path = os.path.join(logs_dir, "TestRunResults_%s_%s_%s" % (host_os, arch, build_type))
    build_log = log_path + ".log"
    wrn_log = log_path + ".wrn"
    err_log = log_path + ".err"

    msbuild_log_args = ["/fileloggerparameters:\"Verbosity=normal;LogFile=%s\"" % build_log,
                        "/fileloggerparameters1:\"WarningsOnly;LogFile=%s\"" % wrn_log,
                        "/fileloggerparameters2:\"ErrorsOnly;LogFile=%s\"" % err_log,
                        "/consoleloggerparameters:Summary"]

    if g_verbose:
        msbuild_log_args += ["/verbosity:diag"]

    command += msbuild_log_args

    command += ["/p:__BuildOS=%s" % host_os,
                "/p:__BuildArch=%s" % arch,
                "/p:__BuildType=%s" % build_type,
                "/p:__LogsDir=%s" % logs_dir]

    print " ".join(command)
    proc = subprocess.Popen(command)
    proc.communicate()

    return proc.returncode

def copy_native_test_bin_to_core_root(host_os, path, core_root):
    """ Recursively copy all files to core_root
    
    Args:
        host_os(str)    : os
        path(str)       : native test bin location
        core_root(str)  : core_root location
    """
    assert os.path.isdir(path) or os.path.isfile(path)
    assert os.path.isdir(core_root)

    extension = "so" if host_os == "Linux" else "dylib"

    if os.path.isdir(path):
        for item in os.listdir(path):
            copy_native_test_bin_to_core_root(host_os, os.path.join(path, item), core_root)
    elif path.endswith(extension):
        print "cp -p %s %s" % (path, core_root)
        shutil.copy2(path, core_root) 

def run_tests(host_os,
              arch,
              build_type, 
              core_root,
              coreclr_repo_location, 
              test_location, 
              test_native_bin_location, 
              test_env=None,
              is_long_gc=False,
              is_gcsimulator=False,
              is_jitdasm=False,
              is_ilasm=False,
              run_sequential=False):
    """ Run the coreclr tests
    
    Args:
        host_os(str)                : os
        arch(str)                   : arch
        build_type(str)             : configuration
        coreclr_repo_location(str)  : path to the root of the repo
        core_root(str)              : Core_Root path
        test_location(str)          : Test bin, location
        test_native_bin_location    : Native test components, None and windows.
        test_env(str)               : path to the test_env to be used
    """

    # Copy all the native libs to core_root
    if host_os != "Windows_NT":
        copy_native_test_bin_to_core_root(host_os, os.path.join(test_native_bin_location, "src"), core_root)

    # Setup the dotnetcli location
    dotnetcli_location = os.path.join(coreclr_repo_location, "Tools", "dotnetcli", "dotnet%s" % (".exe" if host_os == "Windows_NT" else ""))

    # Setup the environment
    if is_long_gc:
        print "Running Long GC Tests, extending timeout to 20 minutes."
        os.environ["__TestTimeout"] = "1200000" # 1,200,000
        os.environ["RunningLongGCTests"] = "1"
    
    if is_gcsimulator:
        print "Running GCSimulator tests, extending timeout to one hour."
        os.environ["__TestTimeout"] = "3600000" # 3,600,000
        os.environ["RunningGCSimulatorTests"] = "1"

    if is_jitdasm:
        print "Running jit disasm on framework and test assemblies."
        os.environ["RunningJitDisasm"] = "1"

    if is_ilasm:
        print "Running ILasm round trip."
        os.environ["RunningIlasmRoundTrip"] = "1"

    # Set Core_Root
    os.environ["CORE_ROOT"] = core_root

    # Call msbuild.
    return call_msbuild(coreclr_repo_location,
                        dotnetcli_location,
                        host_os,
                        arch,
                        build_type,
                        sequential=run_sequential)

def setup_args(args):
    """ Setup the args based on the argparser obj

    Args:
        args(ArgParser): Parsed arguments

    Notes:
        If there is no core_root, or test location passed, create a default
        location using the build type and the arch.
    """

    host_os = None
    arch = args.arch.lower()
    build_type = args.build_type

    test_location = args.test_location
    core_root = args.core_root
    test_native_bin_location = args.test_native_bin_location

    coreclr_repo_location = args.coreclr_repo_location
    if os.path.basename(coreclr_repo_location) == "tests":
        coreclr_repo_location = os.path.dirname(coreclr_repo_location)
   
    if _platform == "linux" or _platform == "linux2":
        host_os = "Linux"
    elif _platform == "darwin":
        host_os = "OSX"
    elif _platform == "win32":
        host_os = "Windows_NT"
    else:
        print "Unknown OS: %s" % host_os
        sys.exit(1)

    assert os.path.isdir(coreclr_repo_location)

    valid_arches = ["x64", "x86", "arm", "arm64"]
    if not arch in valid_arches:
        print "Unsupported architecture: %s." % arch
        print "Supported architectures: %s" % "[%s]" % ", ".join(valid_arches)
        sys.exit(1)

    valid_build_types = ["Debug", "Checked", "Release"]
    if build_type != None and len(build_type) > 0:
        # Force the build type to be capitalized
        build_type = build_type.capitalize()

    if not build_type in valid_build_types:
        print "Unsupported configuration: %s." % build_type
        print "Supported configurations: %s" % "[%s]" % ", ".join(valid_build_types)
        sys.exit(1)

    if test_location is None:
        default_test_location = os.path.join(coreclr_repo_location, "bin", "tests", "%s.%s.%s" % (host_os, arch, build_type))
        
        if os.path.isdir(default_test_location):
            test_location = default_test_location

            print "Using default test location."
            print "TestLocation: %s" % default_test_location
            print

        else:
            # The tests for the default location have not been built.
            print "Error, unable to find the tests at %s" % default_test_location

            suggested_location = None
            possible_test_locations = [item for item in os.listdir(os.path.join(coreclr_repo_location, "bin", "tests")) if host_os in item and arch in item]
            if len(possible_test_locations) > 0:
                print "Tests are built for the following:"
                for item in possible_test_locations:
                    print item.replace(".", " ")
                
                print "Please run runtest.py again with the correct build-type by passing -build_type"
            else:
                print "No tests have been built for this host and arch. Please run build-test.%s" % ("cmd" if host_os == "Windows_NT" else "sh")
                sys.exit(1)

    if core_root is None:
        default_core_root = os.path.join(test_location, "Tests", "Core_Root")

        if os.path.isdir(default_core_root):
            core_root = default_core_root

            print "Using default location for core_root."
            print "Core_Root: %s" % core_root
            print

        else:
            # CORE_ROOT has not been setup correctly.
            print "Error, unable to find CORE_ROOT at %s" % default_core_root
            print "Please run build-test.cmd %s %s generatelayoutonly" % (arch, build_type)

            sys.exit(1)

    if host_os != "Windows_NT":
        if test_native_bin_location is None:
            print "Using default location for test_native_bin_location."
            test_native_bin_location = os.path.join(os.path.join(coreclr_repo_location, "bin", "obj", "%s.%s.%s" % (host_os, arch, build_type), "tests"))
            print "Native bin location: %s" % test_native_bin_location
            print

    if host_os != "Windows_NT":
        if not os.path.isdir(test_native_bin_location):
            print "Error, test_native_bin_location: %s, does not exist." % test_native_bin_location
            sys.exit(1)

    return host_os, arch, build_type, coreclr_repo_location, core_root, test_location, test_native_bin_location

def setup_tools(host_os, coreclr_repo_location):
    """ Setup the tools for the repo

    Args:
        host_os(str)                : os
        coreclr_repo_location(str)  : path to coreclr repo

    """

    # Is the tools dir setup
    setup = False
    tools_dir = os.path.join(coreclr_repo_location, "Tools")

    is_windows = host_os == "Windows_NT"

    dotnetcli_location = os.path.join(coreclr_repo_location, "Tools", "dotnetcli", "dotnet%s" % (".exe" if host_os == "Windows_NT" else ""))

    if os.path.isfile(dotnetcli_location):
        setup = True
    
    # init the tools for the repo
    if not setup:
        command = None
        if is_windows:
            command = [os.path.join(coreclr_repo_location, "init_tools.cmd")]
        else:
            command = ["sh", os.path.join(coreclr_repo_location, "init_tools.sh")]

        print " ".join(command)
        subprocess.check_output(command)
    
        setup = True

    return setup

def find_test_from_name(host_os, test_location, test_name):
    """ Given a test's name return the location on disk

    Args:
        host_os (str)       : os
        test_location (str) :path to the coreclr tests
        test_name (str)     : Name of the test, all special characters will have
                            : been replaced with underscores.
    
    Return:
        test_path (str): Path of the test based on its name
    """

    location = test_name

    # Lambdas and helpers
    is_file_or_dir = lambda path : os.path.isdir(path) or os.path.isfile(path)
    def match_filename(test_path):
        # Scan through the test directory looking for a similar
        # file
        global file_name_cache

        if not os.path.isdir(os.path.dirname(test_path)):
            pass

        assert os.path.isdir(os.path.dirname(test_path))
        size_of_largest_name_file = 0

        dir_contents = file_name_cache[os.path.dirname(test_path)]

        if dir_contents is None:
            dir_contents = defaultdict(lambda: None)
            for item in os.listdir(os.path.dirname(test_path)):
                dir_contents[re.sub("[" + string.punctuation + "]", "_", item)] = item

            file_name_cache[os.path.dirname(test_path)] = dir_contents

        # It is possible there has already been a match
        # therefore we need to remove the punctuation again.
        basename_to_match = re.sub("[" + string.punctuation + "]", "_", os.path.basename(test_path))
        if basename_to_match in dir_contents:
            test_path = os.path.join(os.path.dirname(test_path), dir_contents[basename_to_match])

        size_of_largest_name_file = len(max(dir_contents, key=len))

        return test_path, size_of_largest_name_file

    # Find the test by searching down the directory list.
    starting_path = test_location
    loc_split = location.split("_")
    append = False
    for index, item in enumerate(loc_split):
        if not append:
            test_path = os.path.join(starting_path, item)
        else:
            append = False
            test_path, size_of_largest_name_file = match_filename(starting_path + "_" + item)

        if not is_file_or_dir(test_path):
            append = True

        # It is possible that there is another directory that is named
        # without an underscore.
        elif index + 1 < len(loc_split) and os.path.isdir(test_path):

            next_test_path = os.path.join(test_path, loc_split[index + 1])
            if not is_file_or_dir(next_test_path):
                added_path = test_path
                for forward_index in range(index + 1, len(loc_split)):
                    added_path, size_of_largest_name_file = match_filename(added_path + "_" + loc_split[forward_index])
                    if is_file_or_dir(added_path):
                        append = True
                        break
                    elif size_of_largest_name_file < len(os.path.basename(added_path)):
                        break
        
        starting_path = test_path

    location = starting_path
    if not os.path.isfile(location):
        pass
    
    assert(os.path.isfile(location))

    return location

def parse_test_results(host_os, arch, build_type, coreclr_repo_location, test_location):
    """ Parse the test results for test execution information

    Args:
        host_os                 : os
        arch                    : architecture run on
        build_type              : build configuration (debug, checked, release)
        coreclr_repo_location   : coreclr repo location
        test_location           : path to coreclr tests

    """

    test_run_location = os.path.join(coreclr_repo_location, "bin", "Logs", "testRun.xml")

    if not os.path.isfile(test_run_location):
        print "Unable to find testRun.xml. This normally means the tests did not run."
        print "It could also mean there was a problem logging. Please run the tests again."

        return

    assemblies = xml.etree.ElementTree.parse(test_run_location).getroot()

    tests = defaultdict(lambda: None)
    for assembly in assemblies:
        for collection in assembly:
            if collection.tag == "errors" and collection.text != None:
                # Something went wrong during running the tests.
                print "Error running the tests, please run runtest.py again."
                sys.exit(1)
            elif collection.tag != "errors":
                test_name = None
                for test in collection:
                    type = test.attrib["type"]
                    method = test.attrib["method"]

                    type = type.split("._")[0]
                    test_name = type + method

                assert test_name != None

                failed = collection.attrib["failed"]
                skipped = collection.attrib["skipped"]
                passed = collection.attrib["passed"]
                time = float(collection.attrib["time"])

                test_location_on_filesystem = find_test_from_name(host_os, test_location, test_name)
                
                assert tests[test_name] == None
                tests[test_name] = {
                    "name": test_name,
                    "test_path": test_location_on_filesystem,
                    "failed": failed,
                    "skipped": skipped,
                    "passed": passed,
                    "time": time
                }

    return tests

def print_summary(tests):
    """ Print a summary of the test results

    Args:
        tests (defaultdict[String]: { }): The tests that were reported by 
                                        : xunit
    
    """

    assert tests is not None

    failed_tests = []
    passed_tests = []
    skipped_tests = []

    for test in tests:
        test = tests[test]

        if test["failed"] == "1":
            failed_tests.append(test)
        elif test["passed"] == "1":
            passed_tests.append(test)
        else:
            skipped_tests.append(test)

    print
    print "Total tests run: %d" % len(tests)
    print
    print "Total passing tests: %d" % len(passed_tests)
    print "Total failed tests: %d" % len(failed_tests)
    print "Total skipped tests: %d" % len(skipped_tests)
    print

    failed_tests.sort(key=lambda item: item["time"], reverse=True)
    passed_tests.sort(key=lambda item: item["time"], reverse=True)
    skipped_tests.sort(key=lambda item: item["time"], reverse=True)

    if len(failed_tests) > 0:
        print "Failed tests:"
        print
        for item in failed_tests:
            time = item["time"]
            unit = "seconds"

            # If it can be expressed in hours
            if time > 60**2:
                time = time / (60**2)
                unit = "hours"

            elif time > 60 and time < 60**2:
                time = time / 60
                unit = "minutes"

            print "%s (%d %s)" % (item["test_path"], time, unit)

    if len(passed_tests) > 50:
        print
        print "50 slowest passing tests:"
        print
        for index, item in enumerate(passed_tests):
            time = item["time"]
            unit = "seconds"

            # If it can be expressed in hours
            if time > 60**2:
                time = time / (60**2)
                unit = "hours"

            elif time > 60 and time < 60**2:
                time = time / 60
                unit = "minutes"

            print "%s (%d %s)" % (item["test_path"], time, unit)

            if index >= 50:
                break

    if len(skipped_tests) > 0:
        print
        print "Skipped tests:"
        print
        for item in skipped_tests:
            time = item["time"]
            unit = "seconds"

            # If it can be expressed in hours
            if time > 60**2:
                time = time / (60**2)
                unit = "hours"

            elif time > 60 and time < 60**2:
                time = time / 60
                unit = "minutes"

            print "%s (%d %s)" % (item["test_path"], time, unit)

def create_repro(host_os, arch, build_type, env, core_root, coreclr_repo_location, tests):
    """ Go through the failing tests and create repros for them

    Args:
        host_os (String)                : os
        arch (String)                   : architecture
        build_type (String)             : build configuration (debug, checked, release)
        core_root (String)              : Core_Root path
        coreclr_repo_location (String)  : Location of coreclr git repo
        tests (defaultdict[String]: { }): The tests that were reported by 
                                        : xunit
    
    """

    print
    print "Creating repo files..."

    assert tests is not None

    failed_tests = [tests[item] for item in tests if tests[item]["failed"] == "1"]
    if len(failed_tests) == 0:
        return
    
    bin_location = os.path.join(coreclr_repo_location, "bin")
    assert os.path.isdir(bin_location)

    repro_location = os.path.join(bin_location, "repro")
    if not os.path.isdir(repro_location):
        print "mkdir %s" % repro_location
        os.mkdir(repro_location)

    assert os.path.isdir(repro_location)

    # Now that the repro_location exists under <coreclr_location>/bin/repro
    # create wrappers which will simply run the test with the correct environment
    for test in failed_tests:
        debug_env = DebugEnv(host_os, arch, build_type, env, core_root, coreclr_repo_location, test)
        debug_env.write_repro()

    print "Repro files written."
    print "They can be found at %s" % repro_location

################################################################################
# Main
################################################################################

def main(args):
    global g_verbose
    g_verbose = args.verbose

    host_os, arch, build_type, coreclr_repo_location, core_root, test_location, test_native_bin_location = setup_args(args)

    env = None
    if not args.analyze_results_only:
        # Setup the tools for the repo.
        setup_tools(host_os, coreclr_repo_location)

        env = get_environment()
        ret_code = create_and_use_test_env(host_os, 
                                        env, 
                                        lambda path: run_tests(host_os, 
                                                                arch,
                                                                build_type,
                                                                core_root, 
                                                                coreclr_repo_location,
                                                                test_location, 
                                                                test_native_bin_location, 
                                                                test_env=path))

        print "Test run finished."

    print "Parsing test results..."
    tests = parse_test_results(host_os, arch, build_type, coreclr_repo_location, test_location)

    if tests is not None:
        print_summary(tests)
        create_repro(host_os, arch, build_type, env, core_root, coreclr_repo_location, tests)

################################################################################
# __main__
################################################################################

if __name__ == "__main__":
    args = parser.parse_args()
    sys.exit(main(args))