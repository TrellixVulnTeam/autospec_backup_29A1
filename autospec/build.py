#!/bin/true
#
# build.py - part of autospec
# Copyright (C) 2015 Intel Corporation
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Actually build the package
#

import os
import re
import shutil
import sys
import subprocess
import util
import shutil
from util import call, write_out, print_fatal, print_debug, print_info, scantree

def cleanup_req(s: str) -> str:
    """Strip unhelpful strings from requirements."""
    if "is wanted" in s:
        s = ""
    if "should be defined" in s:
        s = ""
    if "are broken" in s:
        s = ""
    if "is broken" in s:
        s = ""
    if s[0:4] == 'for ':
        s = s[4:]
    s = s.replace(" works as expected", "")
    s = s.replace(" and usability", "")
    s = s.replace(" usability", "")
    s = s.replace(" argument", "")
    s = s.replace(" environment variable", "")
    s = s.replace(" environment var", "")
    s = s.replace(" presence", "")
    s = s.replace(" support", "")
    s = s.replace(" implementation is broken", "")
    s = s.replace(" is broken", "")
    s = s.replace(" files can be found", "")
    s = s.replace(" can be found", "")
    s = s.replace(" is declared", "")
    s = s.replace("whether to build ", "")
    s = s.replace("whether ", "")
    s = s.replace("library containing ", "")
    s = s.replace("x86_64-generic-linux-gnu-", "")
    s = s.replace("i686-generic-linux-gnu-", "")
    s = s.replace("'", "")
    s = s.strip()
    return s


def check_for_warning_pattern(line):
    """Print warning if a line matches against a warning list."""
    warning_patterns = [
    ]
    for pat in warning_patterns:
        if pat in line:
            util.print_warning("Build log contains: {}".format(pat))


def get_mock_cmd():
    """Set mock command to use sudo as needed."""
    # Some distributions (e.g. Fedora) use consolehelper to run mock,
    # while others (e.g. Clear Linux) expect the user run it via sudo.
    if os.path.basename(os.path.realpath('/usr/bin/mock')) == 'consolehelper':
        return 'PYTHONMALLOC=malloc MIMALLOC_PAGE_RESET=0 MIMALLOC_LARGE_OS_PAGES=1 LD_PRELOAD=/usr/lib64/libmimalloc.so /usr/bin/mock'
    return 'sudo PYTHONMALLOC=malloc MIMALLOC_PAGE_RESET=0 MIMALLOC_LARGE_OS_PAGES=1 LD_PRELOAD=/usr/lib64/libmimalloc.so /usr/bin/mock'


class Build(object):
    """Manage package builds."""

    def __init__(self):
        """Initialize default build settings."""
        self.success = 0
        self.round = 0
        self.must_restart = 0
        self.uniqueext = ''
        self.warned_about = set()
        self.mock_dir = str()
        self.short_circuit = str()

    def write_normal_bashrc(self, mock_dir, content_name, config):
        """Write normal bashrc to package builddir home directory."""
        builddir_home_dst = f"{mock_dir}/clear-{content_name}/root/builddir/.bashrc"
        normal_bashrc_file = "/aot/build/clearlinux/projects/autospec/autospec/normal_bashrc"

        if os.path.isfile(normal_bashrc_file) and not config.config_opts.get("custom_bashrc"):
            shutil.copy2(normal_bashrc_file, builddir_home_dst)
        elif config.config_opts.get("custom_bashrc") and config.custom_bashrc_file and os.path.isfile(config.custom_bashrc_file):
            shutil.copy2(config.custom_bashrc_file, builddir_home_dst)
        #else:
            #util.print_fatal("Failed to move custom .bashrc to chroot home dir")
            #sys.exit(1)

    def write_python_flags_fix(self, mock_dir, content_name, config):
        """Patch python to use custom flags."""
        python_dir_dst = f"{mock_dir}/clear-{content_name}/root/usr/lib/python3.9"
        python_dir_patched_file = f"{python_dir_dst}/patched"
        patch_file = "/aot/build/clearlinux/projects/autospec/autospec/0001-Fix-PYTHON-flags.patch"
        patch_cmd = f"sudo /usr/bin/patch --backup -p1 --fuzz=2 --input={patch_file}"
        if not os.path.isfile(python_dir_patched_file):
            try:
                process = subprocess.run(
                    patch_cmd,
                    check=True,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    universal_newlines=True,
                    cwd=python_dir_dst,
                )
            except subprocess.CalledProcessError as err:
                revert_patch = [(f.path, f.path.replace(".orig", "")) for f in scantree(python_dir_dst) if f.is_file() and os.path.splitext(f.name)[1].lower() == ".orig"]
                for pcs in revert_patch:
                    process = subprocess.run(
                        f"sudo cp {pcs[0]} {pcs[1]}",
                        check=False,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        universal_newlines=True,
                        cwd=python_dir_dst,
                    )
                print_fatal(f"Unable to patch custom flags in {python_dir_dst}: {err}")
                sys.exit(1)
            process = subprocess.run(
                f"echo patched | sudo tee patched",
                check=False,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                universal_newlines=True,
                cwd=python_dir_dst,
            )

    def simple_pattern_pkgconfig(self, line, pattern, pkgconfig, conf32, requirements):
        """Check for pkgconfig patterns and restart build as needed."""
        pat = re.compile(pattern)
        match = pat.search(line)
        if match:
            if self.short_circuit is None:
                self.must_restart += requirements.add_pkgconfig_buildreq(pkgconfig, conf32, cache=True)
            else:
                requirements.add_pkgconfig_buildreq(pkgconfig, conf32, cache=True)

    def simple_pattern(self, line, pattern, req, requirements):
        """Check for simple patterns and restart the build as needed."""
        pat = re.compile(pattern)
        match = pat.search(line)
        if match:
            if self.short_circuit is None:
                self.must_restart += requirements.add_buildreq(req, cache=True)
            else:
                requirements.add_buildreq(req, cache=True)

    def failed_exit_pattern(self, line, config, requirements, pattern, verbose, buildtool=None):
        pat = re.compile(pattern)
        match = pat.search(line)
        if not match:
            return
        #s = match.group(0)
        util.print_extra_warning(f"{line}")

    def failed_pattern(self, line, config, requirements, pattern, verbose, buildtool=None):
        """Check against failed patterns to restart build as needed."""
        pat = re.compile(pattern)
        match = pat.search(line)
        if not match:
            return
        s = match.group(1)
        # standard configure cleanups
        s = cleanup_req(s)

        if s in config.ignored_commands:
            return

        try:
            if not buildtool:
                req = config.failed_commands[s]
                if req:
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq(req, cache=True)
                    else:
                        requirements.add_buildreq(req, cache=True)
            elif buildtool == 'pkgconfig':
                if self.short_circuit is None:
                    self.must_restart += requirements.add_pkgconfig_buildreq(s, config.config_opts.get('32bit'), cache=True)
                else:
                    requirements.add_pkgconfig_buildreq(s, config.config_opts.get('32bit'), cache=True)
            elif buildtool == 'R':
                if requirements.add_buildreq("R-" + s, cache=True) > 0:
                    if self.short_circuit is None:
                        self.must_restart += 1
                    requirements.add_requires("R-" + s, config.os_packages, cache=True)
            elif buildtool == 'perl':
                s = s.replace('inc::', '')
                if self.short_circuit is None:
                    self.must_restart += requirements.add_buildreq('perl(%s)' % s, cache=True)
                else:
                    requirements.add_buildreq('perl(%s)' % s, cache=True)
            elif buildtool == 'pypi':
                s = util.translate(s)
                if not s:
                    return
                if self.short_circuit is None:
                    self.must_restart += requirements.add_buildreq(util.translate('%s-python' % s), cache=True)
                else:
                    requirements.add_buildreq(util.translate('%s-python' % s), cache=True)
            elif buildtool == 'ruby':
                if s in config.gems:
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq(config.gems[s], cache=True)
                    else:
                        requirements.add_buildreq(config.gems[s], cache=True)
                else:
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq('rubygem-%s' % s, cache=True)
                    else:
                        requirements.add_buildreq('rubygem-%s' % s, cache=True)
            elif buildtool == 'ruby table':
                if s in config.gems:
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq(config.gems[s], cache=True)
                    else:
                        requirements.add_buildreq(config.gems[s], cache=True)
                else:
                    print("Unknown ruby gem match", s)
            elif buildtool == 'maven' or buildtool == 'gradle':
                group_count = len(match.groups())
                if group_count == 2:
                    # Add fully qualified versioned mvn() dependency
                    name = match.group(1)
                    # Hyphens are disallowed for version strings, so use dots instead
                    ver = match.group(2).replace('-', '.')
                    mvn_provide = f'mvn({name}) = {ver}'
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq(mvn_provide, cache=True)
                    else:
                        requirements.add_buildreq(mvn_provide, cache=True)
                elif s in config.maven_jars:
                    # Overrides for dependencies with custom grouping
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq(config.maven_jars[s], cache=True)
                    else:
                        requirements.add_buildreq(config.maven_jars[s], cache=True)
                elif group_count == 3:
                    org = match.group(1)
                    name = match.group(2)
                    ver = match.group(3).replace('-', '.')
                    if re.search("-(parent|pom|bom)$", name):
                        mvn_provide = f'mvn({org}:{name}:pom) = {ver}'
                    else:
                        mvn_provide = f'mvn({org}:{name}:jar) = {ver}'
                    if self.short_circuit is None:
                        self.must_restart += requirements.add_buildreq(mvn_provide, cache=True)
                    else:
                        requirements.add_buildreq(mvn_provide, cache=True)
                else:
                    # Fallback to mvn-ARTIFACTID package name
                    self.must_restart += requirements.add_buildreq('mvn-%s' % s, cache=True)
            elif buildtool == 'catkin':
                if self.short_circuit is None:
                    self.must_restart += requirements.add_pkgconfig_buildreq(s, config.config_opts.get('32bit'), cache=True)
                    self.must_restart += requirements.add_buildreq(s, cache=True)
                else:
                    requirements.add_pkgconfig_buildreq(s, config.config_opts.get('32bit'), cache=True)
                    requirements.add_buildreq(s, cache=True)
        except Exception:
            if s.strip() and s not in self.warned_about and s[:2] != '--':
                util.print_warning(f"Unknown pattern match: {s}")
                self.warned_about.add(s)

    def parse_buildroot_log(self, filename, returncode):
        """Handle buildroot log contents."""
        if returncode == 0:
            return True
        self.must_restart = 0
        is_clean = True
        util.call("sync")
        with util.open_auto(filename, "r") as rootlog:
            loglines = rootlog.readlines()
        missing_pat = re.compile(r"^.*No matching package to install: '(.*)'$")
        for line in loglines:
            match = missing_pat.match(line)
            if match is not None:
                util.print_fatal("Cannot resolve dependency name: {}".format(match.group(1)))
                is_clean = False
        return is_clean

    def parse_build_results(self, filename, returncode, filemanager, config, requirements, content):
        """Handle build log contents."""
        requirements.verbose = 1
        self.must_restart = 0
        infiles = 0

        # Flush the build-log to disk, before reading it
        util.call("sync")
        with util.open_auto(filename, "r") as buildlog:
            loglines = buildlog.readlines()
        for line in loglines:
            if self.short_circuit != "prep" and self.short_circuit != "binary":
                for pat in config.pkgconfig_pats:
                    self.simple_pattern_pkgconfig(line, *pat, config.config_opts.get('32bit'), requirements)

                for pat in config.simple_pats:
                    self.simple_pattern(line, *pat, requirements)

                for pat in config.failed_pats:
                    self.failed_pattern(line, config, requirements, *pat)

                for pat in config.failed_exit_pats:
                    self.failed_exit_pattern(line, config, requirements, *pat)

            #check_for_warning_pattern(line)

            # Search for files to add to the %files section.
            # * infiles == 0 before we reach the files listing
            # * infiles == 1 for the "Installed (but unpackaged) file(s) found" header
            #     and for the entirety of the files listing
            # * infiles == 2 after the files listing has ended
            if infiles == 1:
                for search in ["RPM build errors", "Childreturncodewas",
                               "Child returncode", "Empty %files file"]:
                    if search in line:
                        infiles = 2
                for start in ["Building", "Child return code was"]:
                    if line.startswith(start):
                        infiles = 2

            if infiles == 0 and "Installed (but unpackaged) file(s) found:" in line:
                infiles = 1
                filemanager.fix_broken_pkg_config_versioning(content.name)
                if config.config_opts["altcargo1"]:
                    filemanager.write_cargo_find_install_assets(content.name)
            # elif infiles == 1 and "not matching the package arch" not in line:
            elif infiles == 1:
                # exclude blank lines from consideration...
                file = line.strip()
                if file and file[0] == "/":
                    print(f"file: {file}")
                    filemanager.push_file(file, content.name)

            if line.startswith("Sorry: TabError: inconsistent use of tabs and spaces in indentation"):
                print(line)
                returncode = 99

            nvr = f"{content.name}-{content.version}-{content.release}"
            match = f"File not found: /builddir/build/BUILDROOT/{nvr}.x86_64/"
            if match in line:
                missing_file = "/" + line.split(match)[1].strip()
                filemanager.remove_file(missing_file)

            if line.startswith("Executing(%clean") and returncode == 0:
                if self.short_circuit == "binary":
                    print("RPM binary build successful")
                    self.success = 1
                elif self.short_circuit == None:
                    print("RPM build successful")
                    self.success = 1

            if line.startswith("Child return code was: 0") and returncode == 0:
                if self.short_circuit == "prep":
                    print("RPM short circuit prep build successful")
                    self.success = 1
                elif self.short_circuit == "build":
                    print("RPM build build successful")
                    self.success = 1
                elif self.short_circuit == "install":
                    print("RPM install build successful")
                    self.success = 1


    def package(self, filemanager, mockconfig, mockopts, config, requirements, content, mock_dir, short_circuit, cleanup=False):
        """Run main package build routine."""
        self.mock_dir = mock_dir
        self.short_circuit = short_circuit
        self.round += 1
        self.success = 0
        mock_cmd = get_mock_cmd()
        print("Building package " + content.name + " round", self.round)

        self.uniqueext = content.name

        if cleanup:
            cleanup_flag = "--cleanup-after"
        else:
            cleanup_flag = "--no-cleanup-after"

        print("{0} mock chroot at {1}/clear-{2}".format(content.name, mock_dir, self.uniqueext))

        if self.round == 1:
            shutil.rmtree('{}/results'.format(config.download_path), ignore_errors=True)
            os.makedirs('{}/results'.format(config.download_path))

        cmd_args = [
            mock_cmd,
            f"--root={mockconfig}",
            "--buildsrpm",
            "--sources=./",
            f"--spec={content.name}.spec",
            f"--uniqueext={self.uniqueext}",
            "--result=results/",
            cleanup_flag,
            mockopts,
        ]
        util.call(" ".join(cmd_args),
                  logfile=f"{config.download_path}/results/mock_srpm.log",
                  cwd=config.download_path)

        # back up srpm mock logs
        util.call("mv results/root.log results/srpm-root.log", cwd=config.download_path)
        util.call("mv results/build.log results/srpm-build.log", cwd=config.download_path)

        srcrpm = f"results/{content.name}-{content.version}-{content.release}.src.rpm"

        cmd_args = [
            mock_cmd,
            f"--root={mockconfig}",
            "--result=results/",
            srcrpm,
            f"--uniqueext={self.uniqueext}",
            cleanup_flag,
            mockopts,
        ]
        ret = util.call(" ".join(cmd_args),
                        logfile=f"{config.download_path}/results/mock_build.log",
                        check=False,
                        cwd=config.download_path)

        if self.short_circuit == "prep":
            self.write_normal_bashrc(mock_dir, content.name, config)
            self.write_python_flags_fix(mock_dir, content.name, config)

        # sanity check the build log
        if not os.path.exists(config.download_path + "/results/build.log"):
            util.print_fatal("Mock command failed, results log does not exist. User may not have correct permissions.")
            exit(1)

        is_clean = self.parse_buildroot_log(config.download_path + "/results/root.log", ret)
        if is_clean:
            self.parse_build_results(config.download_path + "/results/build.log", ret, filemanager, config, requirements, content)
        if filemanager.has_banned:
            util.print_fatal("Content in banned paths found, aborting build")
            exit(1)
