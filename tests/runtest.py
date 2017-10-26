#!/usr/bin/env python
################################################################################
################################################################################
#
# Module: runtest.py
#
# Notes:
#
# Intermediate test runner to replace runtest.sh
#
################################################################################
################################################################################

import argparse
import contextlib
import errno
import locale
import json
import math
import multiprocessing
import os
import platform
import urllib
import urllib2
import shutil
import tempfile
import subprocess
import sys
import tarfile
import zipfile

from collections import defaultdict
from multiprocessing import Process, Queue, Pipe, Lock

################################################################################
# Argument Parser
################################################################################

description = """Intermediate test runner to replace runtest.sh
              """

parser = argparse.ArgumentParser(description=description)

parser.add_argument("-arch", dest="arch", nargs='?', default=None),
parser.add_argument("-build_type", dest="build_type", nargs='?', default=None)
parser.add_argument("-os", dest="host_os", nargs='?', default=None)

parser.add_argument("-bin_dir", dest="bin_dir", nargs='?', default=None)
parser.add_argument("-product_dir", dest="product_dir", nargs='?', default=None)
parser.add_argument("-test_dir", dest="test_dir", nargs='?', default=None)
parser.add_argument("-test_native_dir", dest="test_native_dir", nargs='?', default=None)
parser.add_argument("-mscorlib_dir", dest="mscorlib_dir", nargs='?', default=None)
parser.add_argument("-corefx_dir", dest="corefx_dir", nargs='?', default=None)
parser.add_argument("-coreoverlay_dir", dest="coreoverlay_dir", nargs='?', default=None)
parser.add_argument("-subset_test_dirs", dest="subset_test_dirs", nargs='?', default=None)
parser.add_argument("-env", dest="env", nargs='?', default=None)

parser.add_argument("--build_overlay_only", dest="build_overlay_only", action="store_true", default=False)
parser.add_argument("--sequential", dest="sequential", action="store_true", default=False)
parser.add_argument("--verbose", dest="verbose", action="store_true", default=False)
parser.add_argument("--force_release_corefx", dest="force_release_corefx", action="store_true", default=False)

################################################################################
# Classes
################################################################################

class Arguments:
    """ Arguments nicely set up for the script
    """

    def __init__(self,
                 bin_dir,
                 arch=None,
                 build_type=None,
                 host_os=None,
                 product_dir=None,
                 test_dir=None,
                 test_native_dir=None,
                 mscorlib_dir=None,
                 corefx_dir=None,
                 coreoverlay_dir=None,
                 subset_test_dirs=None,
                 env = None,
                 sequential=False,
                 verbose=False,
                 build_overlay_only=False,
                 force_release_corefx=False
                ):
        """ Init the arguments
        """

        self.verbose = verbose
        self.sequential = sequential
        self.build_overlay_only = build_overlay_only
        self.force_release_corefx = force_release_corefx

        self.bin_dir = bin_dir
        self.arch = arch
        self.build_type = build_type
        self.host_os = host_os
        self.product_dir = product_dir
        self.test_dir = test_dir
        self.test_native_dir = test_native_dir
        self.mscorlib_dir = mscorlib_dir
        self.corefx_dir = corefx_dir
        self.coreoverlay_dir = coreoverlay_dir
        self.env = env
        self.subset_test_dirs = subset_test_dirs

        # Let the getters setup defaults if there are any.
        self.arch = self.get_arch()
        self.build_type = self.get_build_type()
        self.host_os = self.get_os()

        self.product_dir = self.get_product_dir()
        self.test_dir = self.get_test_dir()
        self.test_native_dir = self.get_test_native_dir()

        self.mscorlib_dir = self.get_mscorlib_dir()
        self.corefx_dir = self.get_corefx_dir()
        self.coreoverlay_dir = self.get_coreoverlay_dir()
        self.env = self.get_env()

        valid_arch_list = ["x86", "arm64", "arm", "x64"]
        valid_os_list = ["OSX", "Linux", "Windows"]
        valid_build_type_list = ["Debug", "Checked", "Release"]

        assert(os.path.isdir(self.bin_dir))
        assert(self.arch in valid_arch_list)
        assert(self.host_os in valid_os_list)
        assert(os.path.isdir(self.product_dir))
        assert(os.path.isdir(self.test_dir))
        assert(os.path.isdir(self.test_native_dir))
        assert(os.path.isdir(self.mscorlib_dir))

        if self.verbose:
            print "Arch: %s" % self.arch
            print "Build Type: %s" % self.build_type
            print "Host OS: %s" % self.host_os

            print
            print "Bin Dir: %s" % self.bin_dir
            print "Product Dir: %s" % self.product_dir
            print "Test Dir: %s" % self.test_dir
            print "Test Native Dir: %s" % self.test_native_dir

            print
            print "MSCorLib Dir: %s" % self.mscorlib_dir
            print "CoreFX Dir: %s" % self.corefx_dir

    def get_arch(self):
        """ Get the architecture for the current machine
        """

        if self.arch is None:
            arch_map = {
                "x86_64": "x64",
                "i386": "x86",
                "aarch64": "arm64",
                "armhf": "arm"
            }

            assert(platform.machine() in arch_map)
            return arch_map[platform.machine()]

        else:
            return self.arch

    def get_build_type(self):
        """ Get the default build type
        """

        if self.build_type is None:
            return "Debug"
        else:
            return self.build_type

    def get_os(self):
        """ Get the current os
        """

        if self.host_os is None:
            os_map = {
                "Linux": "Linux",
                "Windows": "Windows",
                "Darwin": "OSX"
            }

            assert(platform.system() in os_map)
            return os_map[platform.system()]
        else:
            return self.host_os

    def get_product_dir(self):
        """ Get the product dir
        """

        if self.product_dir is None:
            return os.path.join(self.bin_dir, 
                                "Product", 
                                "%s.%s.%s" % (self.get_os(), 
                                              self.get_arch(), 
                                              self.get_build_type()
                                             )
                               )
        else:
            return self.product_dir

    def get_test_dir(self):
        """ Get the test dir
        """

        if self.test_dir is None:
            return os.path.join(self.bin_dir, 
                                "tests", 
                                "%s.%s.%s" % (self.get_os(), 
                                              self.get_arch(), 
                                              self.get_build_type()
                                             )
                               )
        else:
            return self.test_dir
        
    def get_test_native_dir(self):
        """ Get the test native dir
        """

        if self.test_native_dir is None:
            return os.path.join(self.bin_dir, 
                                "obj", 
                                "%s.%s.%s" % (self.get_os(), 
                                              self.get_arch(), 
                                              self.get_build_type()
                                             ), 
                                "tests"
                               )
        else:
            return self.test_native_dir

    def get_mscorlib_dir(self):
        """ Get the mscorlib dir
        """

        if self.mscorlib_dir is None:
            return os.path.join(self.bin_dir, 
                                "Product", 
                                "%s.%s.%s" % (self.get_os(), 
                                              self.get_arch(), 
                                              self.get_build_type()
                                             )
                               )
        else:
            return self.mscorlib_dir

    def get_corefx_dir(self):
        """ Get the CoreFX dir
        """

        if self.corefx_dir is None:
            return None
        else:
            return self.corefx_dir
    
    def get_coreoverlay_dir(self):
        """ Get the coreoverlay dir
        """

        if self.coreoverlay_dir is None:
            overlay_dir = os.path.join(self.test_dir, "Tests", "coreoverlay")

            if not os.path.isdir(overlay_dir):
                os.mkdir(overlay_dir)
            
            return overlay_dir
        else:
            if not os.path.isdir(self.coreoverlay_dir):
                os.mkdir(self.coreoverlay_dir)

            return self.coreoverlay_dir

    def get_env(self):
        """ Get the env
        """

        if self.env is None:
            return None

        if not os.path.isfile(self.env):
            raise Exception("Error, env is expected to be a json file.")

        else:
            with open(self.env) as json_file_handle:
                obj = json.load(json_file_handle)

                try:
                    assert isinstance(obj, list)

                    for item in obj:
                        assert item.has_key("name")
                        assert item.has_key("value")

                except:
                    raise Exception("Error, invalid json env. Must follow the pattern:\n[\n   {\n      'name': 'COMPlus_JitMinOpts',\n      'value': '1'\n   }\n]")

                return obj


################################################################################
# Helper Functions
################################################################################

def build_coreoverlay(arch,
                      build_type,
                      host_os,
                      coreoverlay_dir,
                      product_dir,
                      corefx_dir,
                      mscorlib_dir,
                      force_release_corefx,
                      verbose
                     ):
    """ Build the coreoverlay directory
    """

    if verbose:
        print "Copying coreclr product directory"

    # Pull down the latest corefx packages, or copy the locally built
    # corefx.
    if corefx_dir is None:
        # Pull down and untar the most recently built corefx

        if build_type == "Debug" and not force_release_corefx:
            build_type = "Debug"
        else:
            build_type = "Release"

        os_map = {
            "OSX": "osx10.12",
            "Linux": "ubuntu14.04"
        }

        if host_os == "Windows":
            raise NotImplementedError("NYI: build overlay Windows")

        job_name = "%s_%s" % (os_map[host_os], build_type.lower())

        if arch == "arm":
            job_name = "linux_arm_cross_%s" % build_type.lower()
        
        if verbose:
            print "Using job name: %s for corefx" % job_name

        job_uri = "https://ci.dot.net/job/dotnet_corefx/job/master/job/%s/lastSuccessfulBuild/artifact/bin/build.tar.gz" % job_name

        @contextlib.contextmanager
        def tempdir():
            dirpath = tempfile.mkdtemp()
            def cleanup():
                shutil.rmtree(dirpath)

            try:
                yield dirpath
            finally:
                cleanup()

        with tempdir() as dir:
            if verbose:
                print "Downloading %s to %s" % (job_uri, dir)

            urllib.urlretrieve(job_uri, os.path.join(dir, "build.tar.gz"))

            assert (os.path.isfile(os.path.join(dir, "build.tar.gz")))

            if verbose:
                print "CoreFX downloaded successfully."
                print
                print "Untar %s" % os.path.join(dir, "build.tar.gz")
            
            untar_path = os.path.join(dir, "build")
            tar = tarfile.open(os.path.join(dir, "build.tar.gz"))
            tar.extractall(path=untar_path)
            tar.close()

            # For arm64 the corefx native compotents are under bin/corefxNative
            if arch == "arm64":
               corefx_native_path = os.path.join(product_dir, "corefxNative")
               copy_dir(corefx_native_path, untar_path)

            if verbose:
                print "Done."
                print

            copy_dir(untar_path, coreoverlay_dir, verbose)

    else:
        copy_dir(corefx_dir, coreoverlay_dir, verbose)

    # Copy the product directory
    copy_dir(product_dir, coreoverlay_dir, verbose)

    if verbose:
        print "Done."
        print

    # Copy mscorlib
    mscorlib = os.path.join(mscorlib_dir, "System.Private.CoreLib.dll")
    dest = os.path.join (coreoverlay_dir, "System.Private.CoreLib.dll")

    if verbose:
        print "Done."
        print
        print "cp %s %s" % (mscorlib, dest)

    shutil.copy(mscorlib, dest)

def copy_dir(src_dir, dest_dir, verbose=False):
    """ Copy one directory over another
    """
    for item in os.listdir(src_dir):
        src = os.path.join(src_dir, item)
        dest = os.path.join(dest_dir, item)

        if os.path.isdir(src):
            if not os.path.isdir(dest):
                os.mkdir(dest)
            copy_dir(src, dest, verbose)
        
        else:
            if verbose:
                print "cp %s %s" % (src, dest)
            shutil.copy(src, dest)

def copy_over_native_test_components(coreoverlay_dir,
                                     test_native_dir,
                                     verbose
                                    ):
    """ Copy over the native libraries for the tests.
    """

    root_path = os.path.join(test_native_dir, "src")
    
    if verbose:
        print "cp -r %s %s" % (root_path, coreoverlay_dir)
        print

    dylibs = find_all_items(test_native_dir, ".dylib", verbose)

    for item in dylibs:
        src = item
        dest = os.path.join(coreoverlay_dir, os.path.basename(item))

        if verbose:
            print "cp %s %s" % (src, dest)

        shutil.copy(src, dest) 

    if verbose:
        print
        print "Done."
        print

def find_all_items(dir, filetype, verbose):
    """ Scan the dir for filetype
    """

    test_names = []

    for item in os.listdir(dir):
        name = os.path.join(dir, item)

        if os.path.isdir(name):
            test_names += find_all_items(name, filetype, verbose)

        else:
            file_name, extension = os.path.splitext(name)

            if extension == filetype:
                if verbose:
                    print "Adding %s" % name
                test_names.append(name)

    return test_names

def run_tests(arch, test_dir, subset_dir, env, coreoverlay_dir, sequential, verbose):
    """ Run all of the tests.
    """

    unsupported_files = ["testsFailingOutsideWindows.txt",
                         "testsUnsupportedOutsideWindows.txt"
                        ]
    
    if arch == "arm":
        unsupported_files.append("testsUnsupportedOnARM32.txt")
    elif arch == "arm64":
        unsupported_files.append("testsFailingOnArm64.txt")

    skip_tests = []
    for item in unsupported_files:
        with open(item) as file_handle:
            skip_tests += file_handle.readlines()

    tests = defaultdict(lambda: None)

    if verbose:
        print "Scanning for tests..."
        print

    if subset_dir is not None:
        test_dir = os.path.join(test_dir, subset_dir)

    test_names = find_all_items(test_dir, ".sh", verbose)

    if verbose:
        print "Done."
        print

    for test in test_names:
        tests[test] = True

    for test in skip_tests:
        if tests.has_key(test):
            if verbose:
                print "Setting %s to be skipped" % (test)
            tests[test] = False

    # We have a list of all tests to run at this point.
    #
    # We can either run them in parrallel or sequentially.
    def run_test(test, coreoverlay_dir, env, number, total):
        """ Run one test
        """

        def prep_test(test):
            contents = None
            with open(test, 'rU') as file_handle:
                contents = file_handle.read()

            with open(test, "w") as file_handle:
                file_handle.write(contents)

            os.chmod(test, 0775)

        prep_test(test)
        
        working_dir = os.path.dirname(coreoverlay_dir)
        old_working_dir = os.getcwd()

        passed = True

        try:
            print "[%d: %d] %s" % (number, total, test)

            os.environ["CORE_ROOT"] = coreoverlay_dir
            
            if env is not None:
                for item in env:
                    os.environ[item["name"]] = item["value"]

            os.chdir(working_dir)

            args = ["bash", test]
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            std_out, std_err = proc.communicate()

            ret_val = proc.returncode

            if ret_val != 0:
                passed = False
                # lock and print output.
                print std_out

        finally:
            os.chdir(old_working_dir)

        return passed

    if sequential:
        test_list = [item for item in tests if tests[item] is True]

        passed = 0
        failed = 0

        for index, test in enumerate(test_list):
            result = run_test(test, coreoverlay_dir, env, index, len(test_list))

            if result:
                passed += 1
            else:
                failed += 1

        print "Passed: %d" % passed
        print "Failed: %d" % failed
    else:
        thread_count = multiprocessing.cpu_count()
        std_out_lock = Lock()

        def run_test_list(test_list, coreoverlay_dir, env, queue):
            passed = 0
            failed = 0

            for index, item in enumerate(test_list):
                result = run_test(item, coreoverlay_dir, env, index + 1, len(test_list))

                if result:
                    passed += 1
                else:
                    failed += 1

            queue.put((passed, failed))

        test_list = [item for item in tests if tests[item] is True]

        procs = []
        for index in range(thread_count):
            step = len(test_list) / thread_count

            start = index * step
            end = start + step

            if index == thread_count - 1:
                end = len(test_list)

            working_tests = test_list[start:end]
            queue = Queue()
            procs.append((queue, Process(target=run_test_list, args=(working_tests, coreoverlay_dir, env, queue))))

        for proc in procs:
            proc[1].start()

        total_passed = 0
        total_failed = 0
        for index, proc in enumerate(procs):
            proc[1].join()
            passed, failed = proc[0].get()

            total_failed += failed
            total_passed += passed

        print "Passed: %d" % total_passed
        print "Failed: %d" % total_failed

################################################################################
# Main
################################################################################

def main(args):
    args = Arguments(args.bin_dir,
                     args.arch,
                     args.build_type,
                     args.host_os,
                     args.product_dir,
                     args.test_dir,
                     args.test_native_dir,
                     args.mscorlib_dir,
                     args.corefx_dir,
                     args.coreoverlay_dir,
                     args.subset_test_dirs,
                     args.env,
                     args.sequential,
                     args.verbose,
                     args.build_overlay_only,
                     args.force_release_corefx)

    build_coreoverlay(args.arch,
                      args.build_type,
                      args.host_os,
                      args.coreoverlay_dir, 
                      args.product_dir, 
                      args.corefx_dir, 
                      args.mscorlib_dir,
                      args.force_release_corefx,
                      args.verbose)

    if args.build_overlay_only:
        return 0

    copy_over_native_test_components(args.coreoverlay_dir,
                                     args.test_native_dir,
                                     args.verbose)

    run_tests(args.arch,
              args.test_dir,
              args.subset_test_dirs,
              args.env,
              args.coreoverlay_dir,
              args.sequential,
              args.verbose
             )

################################################################################
# setup for Main
################################################################################

if __name__ == "__main__":
   args = parser.parse_args(sys.argv[1:])
   sys.exit(main(args))
