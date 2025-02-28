#!/usr/bin/python3
#
# specfile.py - part of autospec
# Copyright (C) 2016 Intel Corporation
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
# Write spec file
#

import mmap
import os
import re
import time
import types
import shutil
import util
import sys
from collections import OrderedDict

from util import _file_write
from util import open_auto


class Specfile(object):
    """Holds data and methods needed to write the spec file."""

    def __init__(self, url, version, name, release, config, requirements, content, mock_dir, short_circuit):
        """Add default information for specfile template."""
        self.url = url
        self.version = version
        self.name = name
        self.release = release
        self.config = config
        self.requirements = requirements
        self.content = content
        self.specfile = None
        self.source_index = {}
        self.default_sum = ""
        self.hashes = dict()
        self.licenses = []
        self.license_files = []
        self.packages = OrderedDict()
        self.subpackages = OrderedDict()
        self.default_desc = ""
        self.locales = []
        self.build_dirs = dict()  # Build directories, indexed by source URL
        self.golibpath = ""
        self.need_avx2_flags = False
        self.need_avx512_flags = False
        self.tests_config = ""
        self.excludes = []
        self.file_maps = {}
        self.keyid = ""
        self.email = ""
        self.extra_cmake = config.extra_cmake + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_32 = config.extra_cmake_32 + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_64 = config.extra_cmake_64 + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_special = config.extra_cmake_special + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_special2 = config.extra_cmake_special2 + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_pgo = config.extra_cmake_pgo + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_special_pgo = config.extra_cmake_special_pgo + " " + " ".join(requirements.extra_cmake)
        #self.cmake_macro = config.cmake_macro + " " + " ".join(requirements.extra_cmake)
        #self.cmake_macro_pgo = config.cmake_macro_pgo + " " + " ".join(requirements.extra_cmake)
        #self.cmake_macro_32 = config.cmake_macro_32 + " " + " ".join(requirements.extra_cmake)
        #self.cmake_macro_special = config.cmake_macro_special + " " + " ".join(requirements.extra_cmake)
        self.extra_cmake_openmpi = config.extra_cmake_openmpi + " " + " ".join(requirements.extra_cmake_openmpi)
        self.cargo_install_assets : List[Tuple[str, str, str]] = list()
        self.mock_dir : str = mock_dir
        self.short_circuit : str = short_circuit

    def read_file(self, path):
        """Read full file at path.

        If the file does not exist (or is not expected to exist)
        in the package git repo, specify 'track=False'.
        """
        try:
            with open(path, "r") as f:
                return f.readlines()
        except EnvironmentError:
            return []

    def read_script_file(self, path):
        """Read RPM script snippet file at path.

        Returns verbatim, except for possibly the first line.

        If the config file does not exist (or is not expected to exist)
        in the package git repo, specify 'track=False'.
        """
        lines = self.read_file(path)
        if len(lines) > 0 and (lines[0].startswith("#!") or lines[0].startswith("# -*- ")):
            lines = lines[1:]
        # Remove any trailing whitespace and newlines. The newlines are later
        # restored by writer functions.
        return [line.rstrip() for line in lines]

    def write_spec(self):
        """Write spec file."""
        self.specfile = open_auto("{}/{}.spec".format(self.config.download_path, self.name), "w")
        self.specfile.write_strip = types.MethodType(_file_write, self.specfile)

        # spec file comment header
        self.write_comment_header()

        if self.config.config_opts.get("keepstatic"):
            self._write("%define keepstatic 1\n")

        #if self.config.config_opts.get("filters_provreq"):
            #filters = self.read_script_file(os.path.join(os.path.dirname(__file__), "filters_provreq"))
            #for line in filters:
                #self._write("{}\n".format(line))

        # general package header
        self.write_nvr()
        self.write_sources()
        self.write_summary()
        self.write_license()

        self.write_main_subpackage_requires()
        self.write_main_subpackage_standalone_requires()
        self.write_buildreq()
        self.write_strip_command()
        self.write_debug_command()
        self.write_missing_build_ids_command()
        self.write_disable_autoreq()
        self.write_disable_autoprov()
        self.write_patch_header()

        # main package extra content
        self.write_description()
        self.write_files_header()

        # build instructions
        self.write_buildpattern()

        # scriplets
        self.write_scriplets()

        # %files
        self.write_files()
        self.write_lang_files()

        self.specfile.close()

    def write_comment_header(self):
        """Write comment header to spec file."""
        self._write("#\n")
        self._write("# This file is auto-generated. DO NOT EDIT\n")
        self._write("# Generated by: autospec.py\n")
        self._write("#\n")

        # if package was verified, write public key information
        if self.keyid:
            sig_msg = "# Source0 file verified with key 0x{}".format(self.keyid)
            if self.email:
                sig_msg += " ({})".format(self.email)

            self._write_strip(sig_msg)
            self._write_strip("#")

    def write_nvr(self):
        """Write name, version, and release information."""
        if self.config.urlban:
            clean_url = re.sub(self.config.urlban, "localhost", self.url)
            # Duplicate prefixes entry before we change the url
            self.content.prefixes[clean_url] = self.content.prefixes.get(self.url)
            self.url = clean_url
        self._write("Name     : {}\n".format(self.name))
        self._write("Version  : {}\n".format(self.version))
        self._write("Release  : {}\n".format(str(self.release)))
        self._write("URL      : {}\n".format(self.url))
        if not self.config.default_pattern == "godep":
            self._write("Source0  : {}\n".format(self.url))

    def write_sources(self):
        """Append additional source files.

        Append systemd unit files, gcov, and additional source tarballs are the currently supported file types.
        """
        count = 0
        for source in sorted(
            self.config.sources["version"]
            + self.config.sources["unit"]
            + self.config.sources["archive"]
            + self.config.sources["tmpfile"]
            + self.config.sources["sysuser"]
            + self.config.sources["gcov"]
            + self.config.sources["godep"]
        ):
            count += 1
            self.source_index[source] = count
            if self.config.urlban:
                source = re.sub(self.config.urlban, "localhost", source)
            self._write("Source{0}  : {1}\n".format(count, source))

        # if package is verified, include the signature in the source tarball
        if self.keyid and self.config.signature:
            count += 1
            self._write_strip(f"Source{count}  : {self.config.signature}")

        for source in self.config.extra_sources:
            count += 1
            self._write("Source{0}  : {1}\n".format(count, source[0]))

    def write_summary(self):
        """Write package summary to spec file."""
        if len(self.default_sum.strip()) < 1:
            self.default_sum = "No summary provided"
        self._write("Summary  : {}\n".format(self.default_sum.strip()))
        self._write("Group    : Development/Tools\n")

    def write_license(self):
        """Write license information to spec file."""
        self._write("License  : {}\n".format(" ".join(sorted(self.licenses))))

    def write_main_subpackage_requires(self):
        """Write subpackage build requirements."""
        for pkg in sorted(self.packages):
            if pkg == "autostart" and self.config.config_opts.get("no_autostart"):
                continue
            if pkg.startswith("extras-"):
                continue
            if pkg in ["ignore", "main", "dev", "active-units", "extras", "lib32", "dev32", "doc", "examples", "abi", "staticdev", "staticdev32", "tests"]:
                continue
            # honor requires_ban for manual overrides
            if "{}-{}".format(self.name, pkg) in self.requirements.banned_requires.get(None, []):
                continue
            self._write("Requires: {}-{} = %{{version}}-%{{release}}\n".format(self.name, pkg))

        for pkg in sorted(self.requirements.requires.get(None, [])):
            if "{}".format(self.name, pkg) in self.requirements.banned_requires.get(None, []):
                continue
            self._write("Requires: {}\n".format(pkg))
        for pkg in sorted(self.requirements.provides.get(None, [])):
            self._write("Provides: {}\n".format(pkg))

    def write_main_subpackage_standalone_requires(self):
        """Write subpackage build requirements."""
        for pkg in sorted(self.subpackages):
            # honor requires_ban for manual overrides
            if "{}".format(self.name, pkg) in self.requirements.banned_requires.get(None, []):
                continue
            self._write("Requires: {} = %{{version}}-%{{release}}\n".format(pkg))

    def write_buildreq(self):
        """Write build requirements."""
        for req in sorted(self.requirements.buildreqs):
            self._write("BuildRequires : {}\n".format(req))

    def write_strip_command(self):
        """Write commands to prevent stripping binary if requested."""
        if self.config.config_opts["nostrip"]:
            self._write("# Suppress stripping binaries\n")
            self._write("%define __strip /bin/true\n%define debug_package %{nil}\n")

    def write_debug_command(self):
        """Write commands to prevent debug info generation if requested."""
        if self.config.config_opts["nodebug"]:
            self._write("# Suppress generation of debuginfo\n")
            self._write("%global debug_package %{nil}\n")

    def write_missing_build_ids_command(self):
        """Write commands to prevent failure if there are missing build ids."""
        if self.config.config_opts["nomissingbuildids"]:
            self._write("# Ignore missing build ids\n")
            self._write("%undefine _missing_build_ids_terminate_build\n")

    def write_disable_autoreq(self):
        """Write commands to disable automatic requeriments processing."""
        if self.config.config_opts["noautoreq"]:
            self._write("# Disable automatic requeriments processing\n")
            self._write("AutoReq: no\n")

    def write_disable_autoprov(self):
        """Write commands to disable automatic provides processing."""
        if self.config.config_opts["noautoprov"]:
            self._write("# Disable automatic provides processing\n")
            self._write("AutoProv: no\n")

    def write_patch_header(self):
        """Write patch list header."""
        # First loop will set this to 0 when we start. Second loop adds one
        # and picks up from where first loop left off.
        count = -1
        # Write the patches for the primary version as given in Makefile
        for count, patch in enumerate(self.config.patches):
            self._write("Patch{0}: {1}\n".format(count + 1, patch.split()[0]))
        # Write the cargo patches
        for count, patch in enumerate(self.config.patches_cargo):
            self._write("Patch{0}: {1}\n".format(count + 1, patch[0]))
            if len(patch) == 2:
                patch.append(count + 1)
        # Write the version-specific patches
        for version in self.config.verpatches:
            for count, patch in enumerate(self.config.verpatches[version], start=count + 1):
                self._write("Patch{0}: {1}\n".format(count + 1, patch.split()[0]))

    def write_description(self):
        """Write package description."""
        self._write("\n%description\n{}\n".format(self.default_desc.strip()))

    def write_files_header(self):
        """Write file headers to spec file."""
        groups = {}
        groups["dev"] = "Development"
        groups["bin"] = "Binaries"
        groups["lib"] = "Libraries"
        groups["doc"] = "Documentation"
        groups["data"] = "Data"
        groups["services"] = "Systemd services"

        deps = {}
        deps["dev"] = ["lib", "bin", "data"]
        deps["doc"] = ["man", "info"]
        deps["examples"] = ["dev"]
        deps["dev32"] = ["lib32", "bin", "data", "dev"]
        deps["bin"] = ["data", "libexec", "config", "setuid", "attr", "license", "services"]
        deps["lib"] = ["data", "libexec", "license"]
        deps["libexec"] = ["config", "license"]
        deps["lib32"] = ["data", "license"]
        deps["python"] = ["python3"]
        if self.config.config_opts.get("dev_requires_extras"):
            deps["dev"].append("extras")
        if self.config.config_opts.get("openmpi"):
            deps["dev"].append("openmpi")
        for k, v in self.file_maps.items():
            if "requires" in v:
                deps[k] = v["requires"]

        # migration workaround; if we have a python3 package
        # we add an artificial python package

        if ("python3" in self.packages) and ("python" not in self.packages):
            self.packages["python"] = set()

        dev_pkg_exists = False
        if ("dev" in self.packages):
            dev_pkg_exists = True

        dev32_pkg_exists = False
        if ("dev32" in self.packages):
            dev32_pkg_exists = True

        provides = {}
        provides["dev"] = ["devel"]

        for pkg in sorted(self.packages):
            if pkg in ["ignore", "main"]:
                continue

            self._write("\n%package {}\n".format(pkg))
            self._write("Summary: {} components for the {} package.\n".format(pkg, self.name))
            if pkg in groups:
                self._write("Group: {}\n".format(groups[pkg]))
            else:
                self._write("Group: Default\n")

            for dep in deps.get(pkg, []):
                if dep in self.packages:
                    self._write("Requires: {}-{} = %{{version}}-%{{release}}\n".format(self.name, dep))

            for prov in provides.get(pkg, []):
                self._write("Provides: {}-{} = %{{version}}-%{{release}}\n".format(self.name, prov))

            if pkg in ("dev", "perl", "tests"):
                self._write("Requires: {} = %{{version}}-%{{release}}\n".format(self.name))

            if pkg == "staticdev":
                if dev_pkg_exists is True:
                    self._write("Requires: {}-dev = %{{version}}-%{{release}}\n".format(self.name))

            if pkg == "staticdev32":
                if dev32_pkg_exists is True:
                    self._write("Requires: {}-dev32 = %{{version}}-%{{release}}\n".format(self.name))

            if pkg == "python":
                if self.name != self.name.lower():
                    self._write("Provides: {}-python\n".format(self.name.lower()))

            if pkg == "python3":
                self._write("Requires: python3-core\n")
                if self.requirements.pypi_provides:
                    self._write(f"Provides: pypi({self.requirements.pypi_provides})\n")

            for req in sorted(self.requirements.requires.get(pkg, [])):
                self._write(f"Requires: {req}\n")

            for prov in sorted(self.requirements.provides.get(pkg, [])):
                self._write(f"Provides: {prov}\n")

            self.write_disable_autoreq()
            self.write_disable_autoprov()

            self._write("\n%description {}\n".format(pkg))
            self._write("{} components for the {} package.\n".format(pkg, self.name))
            self._write("\n")

        for pkg in sorted(self.subpackages):
            if pkg in ["ignore", "main"]:
                continue

            self._write("\n%package -n {}\n".format(pkg))
            self._write("Summary: {} components for the {} package.\n".format(pkg, self.name))
            if pkg in groups:
                self._write("Group: {}\n".format(groups[pkg]))
            else:
                self._write("Group: Default\n")

            for dep in deps.get(pkg, []):
                if dep in self.subpackages:
                    self._write("Requires: {}-{} = %{{version}}-%{{release}}\n".format(self.name, dep))

            for prov in provides.get(pkg, []):
                self._write("Provides: {}-{} = %{{version}}-%{{release}}\n".format(self.name, prov))

            for req in sorted(self.requirements.requires.get(pkg, [])):
                self._write(f"Requires: {req}\n")

            for prov in sorted(self.requirements.provides.get(pkg, [])):
                self._write(f"Provides: {prov}\n")

            self.write_disable_autoreq()
            self.write_disable_autoprov()

            self._write("\n%description -n {}\n".format(pkg))
            self._write("{} components for the {} package.\n".format(pkg, self.name))
            self._write("\n")

    def write_buildpattern(self):
        """Write build pattern to spec file."""
        self._write_strip("\n")
        pattern_method = getattr(self, "write_{}_pattern".format(self.config.default_pattern))
        if pattern_method:
            pattern_method()

        self.write_source_installs()
        self.write_service_restart()
        self.write_exclude_deletes()
        self.write_install_append()
        if self.config.config_opts["altcargo1"]:
            self.write_cargo_assets()
        # self.write_systemd_units()

    def write_scriplets(self):
        """Write post and pre scripts to spec file."""
        for pkg in sorted(self.packages):
            if pkg in ["ignore", "main", "locales", "locale"]:
                continue
            for script in ["post", "pre"]:
                content = self.config.read_conf_file("{}.{}".format(script, pkg))
                if content:
                    self._write("\n%{0} {1}\n".format(script, pkg))
                    content = ["{}\n".format(line) for line in content]
                    self.specfile.writelines(content)

        for pkg in sorted(self.subpackages):
            if pkg in ["ignore", "main", "locales", "locale"]:
                continue
            for script in ["post", "pre"]:
                content = self.config.read_conf_file("{}.{}".format(script, pkg))
                if content:
                    self._write("\n%{0} {1}\n".format(script, pkg))
                    content = ["{}\n".format(line) for line in content]
                    self.specfile.writelines(content)

    def write_files(self):
        """Write %files section to spec file."""
        self._write("\n%files\n")
        self._write("%defattr(-,root,root,-)\n")
        if "main" in self.packages:
            for filename in sorted(self.packages["main"]):
                self._write("{}\n".format(self.quote_filename(filename)))

        for pkg in sorted(self.packages):
            if pkg in ["ignore", "main", "locales", "locale"]:
                continue

            self._write("\n%files {}\n".format(pkg))
            if pkg in ["doc", "license", "man", "info"]:
                self._write("%defattr(0644,root,root,0755)\n")
            else:
                self._write("%defattr(-,root,root,-)\n")
            for filename in sorted(self.packages[pkg]):
                self._write("{}\n".format(self.quote_filename(filename)))

        for pkg in sorted(self.subpackages):
            if pkg in ["ignore", "main", "locales", "locale"]:
                continue

            self._write("\n%files -n {}\n".format(pkg))
            if pkg in ["doc", "license", "man", "info"]:
                self._write("%defattr(0644,root,root,0755)\n")
            else:
                self._write("%defattr(-,root,root,-)\n")
            for filename in sorted(self.subpackages[pkg]):
                self._write("{}\n".format(self.quote_filename(filename)))

    def write_lang_files(self):
        """Write lang files to spec."""
        if not self.locales:
            return
        if self.name == "gcc" or self.name == "glibc":
            self._write("\n%files locale")
            for lang in self.locales:
                self._write(" -f {}.lang".format(lang))
            self._write("\n%defattr(-,root,root,-)\n")
            for filename in sorted(self.packages["locale"]):
                self._write("{}\n".format(self.quote_filename(filename)))
        else:
            self._write("\n%files locales")
            for lang in self.locales:
                self._write(" -f {}.lang".format(lang))
            self._write("\n%defattr(-,root,root,-)\n")
            for filename in sorted(self.packages["locales"]):
                self._write("{}\n".format(self.quote_filename(filename)))

    def write_lang_c(self, export_epoch=False):
        """Write C language pattern."""
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("export LANG=C.UTF-8")
        if export_epoch:
            # time.time() returns a float, but we only need second-precision
            self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        if self.config.config_opts["asneeded"]:
            self._write_strip("unset LD_AS_NEEDED\n")

    def write_proxy_exports(self):
        """Write proxy exports to localhost to block build/check calls to internet."""
        self._write_strip("unset http_proxy")
        self._write_strip("unset https_proxy")
        self._write_strip("unset no_proxy")
        self._write_strip("export SSL_CERT_FILE=/var/cache/ca-certs/anchors/ca-certificates.crt")

    def write_make_line(self, build32=False, build_type=None, pgo=None, pattern=None):
        """Write make line to spec file."""
        if self.config.trystatic:
            self._write_strip("## trystatic content")
            for line in self.config.trystatic:
                self._write("{}\n".format(line))
            self._write_strip("## trystatic end")
        if build32 is False:
            if self.config.make_prepend:
                self._write_strip("## make_prepend content")
                for line in self.config.make_prepend:
                    self._write("{}\n".format(line))
                self._write_strip("## make_prepend end")
            if self.config.make_prepend64:
                self._write_strip("## make_prepend64 content")
                for line in self.config.make_prepend64:
                    self._write("{}\n".format(line))
                self._write_strip("## make_prepend64 end")
        if build32 is True:
            if self.config.make_prepend32:
                self._write_strip("## make_prepend32 content")
                for line in self.config.make_prepend32:
                    self._write("{}\n".format(line))
                self._write_strip("## make_prepend32 end")
        if build32 is True and build_type is None:
            if not self.config.make_macro_32:
                if self.config.config_opts["use_ninja"]:
                    self._write_strip("ninja --verbose {} {} {}".format(self.config.parallel_build, self.config.extra_make, self.config.extra32_make))
                else:
                    self._write_strip("make {} {} {} V=1 VERBOSE=1".format(self.config.parallel_build, self.config.extra_make, self.config.extra32_make))
            else:
                self._write_strip("## make_macro_32 content")
                for line in self.config.make_macro_32:
                    self._write("{}\n".format(line))
                self._write_strip("## make_macro_32 end")
        elif build32 is False and build_type is None:
            if not self.config.make_macro:
                if self.config.config_opts["use_ninja"]:
                    self._write_strip("ninja --verbose {} {} {}".format(self.config.parallel_build, self.config.extra_make, self.config.extra64_make))
                else:
                    if pattern == "make" and pgo is False:
                        self._write_strip('make {} {} {} V=1 VERBOSE=1 CFLAGS="${{CFLAGS_GENERATE}}" CXXFLAGS="${{CXXFLAGS_GENERATE}}" FFLAGS="${{FFLAGS_GENERATE}}" FCFLAGS="${{FCFLAGS_GENERATE}}" LDFLAGS="${{LDFLAGS_GENERATE}}" LIBS="${{LIBS_GENERATE}}"'.format(self.config.parallel_build, self.config.extra_make, self.config.extra64_make))
                    elif pattern == "make" and pgo is True:
                        self._write_strip('make {} {} {} V=1 VERBOSE=1 CFLAGS="${{CFLAGS_USE}}" CXXFLAGS="${{CXXFLAGS_USE}}" FFLAGS="${{FFLAGS_USE}}" FCFLAGS="${{FCFLAGS_USE}}" LDFLAGS="${{LDFLAGS_USE}}" LIBS="${{LIBS_GENERATE}}"'.format(self.config.parallel_build, self.config.extra_make, self.config.extra64_make))
                    elif pattern == "make" and pgo is None:
                        self._write_strip('make {} {} {} V=1 VERBOSE=1 CFLAGS="${{CFLAGS}}" CXXFLAGS="${{CXXFLAGS}}" FFLAGS="${{FFLAGS}}" FCFLAGS="${{FCFLAGS}}" LDFLAGS="${{LDFLAGS}}" LIBS="${{LIBS_GENERATE}}"'.format(self.config.parallel_build, self.config.extra_make, self.config.extra64_make))
                    elif pattern != "make":
                        self._write_strip("make {} {} {} V=1 VERBOSE=1".format(self.config.parallel_build, self.config.extra_make, self.config.extra64_make))
            else:
                if pgo is True and self.config.make_macro_pgo:
                    self._write_strip("## make_macro_pgo content")
                    for line in self.config.make_macro_pgo:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro_pgo end")
                else:
                    self._write_strip("## make_macro content")
                    for line in self.config.make_macro:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro end")
        elif build32 is False and build_type == "special":
            if not self.config.make_macro_special:
                if self.config.config_opts["use_ninja"]:
                    self._write_strip("ninja --verbose {} {} {}".format(self.config.parallel_build, self.config.extra_make, self.config.extra_make_special))
                else:
                    self._write_strip("make {} {} {} V=1 VERBOSE=1".format(self.config.parallel_build, self.config.extra_make, self.config.extra_make_special))
            else:
                self._write_strip("{}".format(self.config.make_macro_special))
        elif build32 is False and build_type == "special2":
            if not self.config.make_macro_special2:
                if self.config.config_opts["use_ninja"]:
                    self._write_strip("ninja --verbose {} {} {}".format(self.config.parallel_build, self.config.extra_make, self.config.extra_make_special2))
                else:
                    self._write_strip("make {} {} {} V=1 VERBOSE=1".format(self.config.parallel_build, self.config.extra_make, self.config.extra_make_special2))
            else:
                self._write_strip("{}".format(self.config.make_macro_special2))
        if self.config.make_append:
            self._write_strip("## make_append content")
            for line in self.config.make_append:
                self._write("{}\n".format(line))
            self._write_strip("## make_append end")
        if self.config.config_opts["ccstats"]:
            self._write_strip("## ccache stats")
            self._write_strip("ccache -s || : \n")
            self._write_strip("## ccache stats")
        if pgo is True:
            self._write_strip("fi")

    def write_install_openmpi(self):
        """Write make install line (openmpi) to spec file."""
        self._write_strip("module load openmpi")
        if self.config.config_opts["use_ninja"]:
            make_string = "%ninja_install_openmpi"
            self._write_strip("{} {}".format(make_string, self.config.extra_make_install))
        else:
            make_string = "%make_install_openmpi"
            self._write_strip("{} {}".format(make_string, self.config.extra_make_install))
        self._write_strip("module unload openmpi")

    def write_cmake_line_openmpi(self):
        """Write cmake line (openmpi) to spec file."""
        cmake_string = (
            'cmake -G "Unix Makefiles" -DCMAKE_INSTALL_PREFIX=$MPI_ROOT -DCMAKE_INSTALL_SBINDIR=$MPI_BIN \\\n'
            "-DCMAKE_INSTALL_LIBDIR=$MPI_LIB -DCMAKE_INSTALL_INCLUDEDIR=$MPI_INCLUDE -DLIB_INSTALL_DIR=$MPI_LIB \\\n"
            "-DBUILD_SHARED_LIBS:BOOL=ON -DLIB_SUFFIX=64 \\\n"
            "-DCMAKE_AR=/usr/bin/gcc-ar -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_NM=/usr/bin/gcc-nm -DCMAKE_RANLIB=/usr/bin/gcc-ranlib \\\n"
        )
        self._write_strip("{} {} {}".format(cmake_string, self.config.cmake_srcdir, self.extra_cmake_openmpi))

    def write_prep(self, ruby_pattern=False):
        """Write prep section to spec file."""
        self._write_strip("%prep")
        #if self.config.config_opts.get("use_oneapi"):
            #self._write_strip("echo 'intelpython=exclude' > /builddir/oneapi.txt")
            #self._write_strip("grep -qxF 'source /aot/intel/oneapi/setvars.sh --config=/aot/intel/oneapi/config.txt' /builddir/.bashrc || echo 'source /aot/intel/oneapi/setvars.sh --config=/aot/intel/oneapi/config.txt' >> /builddir/.bashrc || :")
        self.write_prep_prepend()
        if ruby_pattern:
            self.build_dirs[self.url] = self.content.gem_subdir
            self._write_strip("gem unpack %{SOURCE0}")
            self._write_strip("%setup -q -D -T -n " + self.content.gem_subdir)
            self._write_strip("gem spec %{{SOURCE0}} -l --ruby > {}.gemspec".format(self.name))
        else:
            if self.config.default_pattern == "godep":
                # No setup needed each source is installed as is
                pass
            else:
                prefix = self.content.prefixes[self.url]
                if self.config.default_pattern == "R":
                    prefix = self.content.tarball_prefix
                    self._write_strip("%setup -q -c -n " + prefix)
                elif prefix:
                    new_prefix = os.path.basename(prefix)
                    if new_prefix and new_prefix.strip() and new_prefix != prefix:
                        self._write_strip(f"%setup -c -n {new_prefix}")
                        self._write_strip(f"find {prefix} -mindepth 1 -name '*' -exec mv -n {{}} ./ \; || :")
                        prefix = new_prefix
                    else:
                        self._write_strip(f"%setup -q -n {prefix}")
                else:
                    # Have to make up a path and create it
                    prefix = os.path.splitext(os.path.basename(self.url))[0]
                    self._write_strip("%setup -q -c -n " + prefix)

                # Keep track of this build dir
                self.build_dirs[self.url] = prefix

                for archive in self.config.sources["archive"]:
                    # Skip POM files - they don't need to be extracted
                    if archive.endswith(".pom"):
                        continue
                    # Also JAR files
                    if archive.endswith(".jar"):
                        continue
                    # Patch files
                    if archive.endswith(".patch"):
                        continue
                    # Handle various archive types
                    extract_cmd = "tar xf {}"
                    if archive.endswith(".zip"):
                        extract_cmd = "unzip -q {}"
                    self._write_strip("cd %{_builddir}")
                    archive_file = os.path.basename(archive)
                    if self.config.archive_details.get(archive + "prefix"):
                        self._write_strip(extract_cmd.format("%{_sourcedir}/" + archive_file))
                    else:
                        # The archive doesn't have a prefix inside, so we have
                        # to create it, then extract the archive under the
                        # created directory, itself beneath BUILD
                        fake_prefix = os.path.splitext(os.path.basename(archive))[0]
                        self._write_strip("mkdir -p {}".format(fake_prefix))
                        self._write_strip("cd {}".format(fake_prefix))
                        self._write_strip(extract_cmd.format("%{_sourcedir}/" + archive_file))

                self._write_strip(f"cd %{{_builddir}}/{self.build_dirs[self.url]}")

                # Now handle extra versions, indexed by SOURCE
                for url in self.config.sources["version"]:
                    prefix = self.content.prefixes[url]
                    if prefix:
                        self._write_strip("cd ..")
                        self._write_strip("%setup -q -T -n {0} -b {1}".format(prefix, self.source_index[url]))
                    else:
                        # Have to make up a path and create it
                        prefix = os.path.splitext(os.path.basename(url))[0]
                        self._write_strip("cd ..")
                        self._write_strip("%setup -q -T -c -n {0} -b {1}".format(prefix, self.source_index[url]))
                    # Keep track of this build dir
                    self.build_dirs[url] = prefix

        for archive, destination in zip(self.config.sources["archive"], self.config.sources["destination"]):
            if destination.startswith(":"):
                continue
            if self.config.archive_details[archive + "prefix"] == self.content.tarball_prefix:
                print("Archive {} already unpacked in {}; ignoring destination".format(archive, self.content.tarball_prefix))
            else:
                self._write_strip("mkdir -p {}".format(destination))

                # Here again, if the archive file has a top-level prefix
                # directory, we simply use it. If not, we have to figure
                # out where we extracted the files instead.
                archive_prefix = self.config.archive_details[archive + "prefix"]
                if not archive_prefix:
                    # Make it up
                    archive_prefix = os.path.splitext(os.path.basename(archive))[0]
                self._write_strip("cp -a %{{_builddir}}/{0}/* %{{_builddir}}/{1}/{2}".format(archive_prefix, self.content.tarball_prefix, destination))
        if self.config.config_opts["altcargo1"]:
            self._write_strip("export CARGO_NET_GIT_FETCH_WITH_CLI=true")
            self._write_strip("export SSL_CERT_FILE=/var/cache/ca-certs/anchors/ca-certificates.crt")
            self._write_strip("export CARGO_HTTP_CAINFO=/var/cache/ca-certs/anchors/ca-certificates.crt")
            self._write_strip("cargo update --verbose")
            self._write_strip("## cargo_update content")
            for line in self.config.cargo_update:
                self._write("{}\n".format(line))
            self._write_strip("## cargo_update end")
            self._write_strip("cargo fetch --verbose")
        self.apply_patches()
        if self.config.default_pattern != "cmake":
            if self.config.config_opts["32bit"]:
                self._write_strip("pushd %{_builddir}")
                self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} build32")
                self._write_strip("popd")
                if self.config.config_opts["build_special_32"]:
                    self._write_strip("pushd %{_builddir}")
                    self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} build-special-32")
                    self._write_strip("popd")
            if self.config.config_opts["build_special"]:
                self._write_strip("pushd %{_builddir}")
                self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} build-special")
                self._write_strip("popd")
            if self.config.config_opts["build_special2"]:
                self._write_strip("pushd %{_builddir}")
                self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} build-special2")
                self._write_strip("popd")
            if self.config.config_opts["use_avx2"]:
                self._write_strip("pushd %{_builddir}")
                self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} buildavx2")
                self._write_strip("popd")
            if self.config.config_opts["use_avx512"]:
                self._write_strip("pushd %{_builddir}")
                self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} buildavx512")
                self._write_strip("popd")
            if self.config.config_opts["openmpi"]:
                self._write_strip("pushd %{_builddir}")
                self._write_strip(f"cp -a %{{_builddir}}/{self.build_dirs[self.url]} build-openmpi")
                self._write_strip("popd")
        self._write_strip("\n")

    def write_32bit_exports(self):
        """Write 32bit only env exports."""
        if self.config.config_opts["fsalt1_32"] and not self.config.config_opts["altflags_pgo_32"]:
            if self.config.altflags1_32f and self.config.altflags1_32f[0]:
                self._write_strip("## altflags1_32f content")
                self._write_strip("unset CFLAGS")
                self._write_strip("unset CXXFLAGS")
                self._write_strip("unset FCFLAGS")
                self._write_strip("unset FFLAGS")
                self._write_strip("unset CFFLAGS")
                self._write_strip("unset LDFLAGS")
                self._write_strip("unset ASFLAGS")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                self._write_strip('export PKG_CONFIG_PATH="/usr/lib32/pkgconfig:/usr/share/pkgconfig"')
                for line in self.config.altflags1_32f:
                    self._write("{}\n".format(line))
                self._write_strip('export ASFLAGS="${ASFLAGS}${ASFLAGS:+ }--32"')
                self._write_strip("## altflags1_32f end")
            elif self.config.altflags1_32 and self.config.altflags1_32[0]:
                self._write_strip("## altflags1_32 content")
                self._write_strip("unset CFLAGS")
                self._write_strip("unset CXXFLAGS")
                self._write_strip("unset FCFLAGS")
                self._write_strip("unset FFLAGS")
                self._write_strip("unset CFFLAGS")
                self._write_strip("unset LDFLAGS")
                self._write_strip("unset ASFLAGS")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                self._write_strip('export PKG_CONFIG_PATH="/usr/lib32/pkgconfig:/usr/share/pkgconfig"')
                for line in self.config.altflags1_32:
                    self._write("{}\n".format(line))
                self._write_strip('export ASFLAGS="${ASFLAGS}${ASFLAGS:+ }--32"')
                self._write_strip("## altflags1_32 end")
        else:
            if self.config.config_opts["use_clang"]:
                self._write_strip("export CC=clang")
                self._write_strip("export CXX=clang++")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                self._write_strip("unset CPATH")
                self._write_strip('export PKG_CONFIG_PATH="/usr/lib32/pkgconfig:/usr/share/pkgconfig"')
                self._write_strip("unset ASFLAGS")
                self._write_strip("unset CFLAGS")
                self._write_strip("unset CXXFLAGS")
                self._write_strip("unset FCFLAGS")
                self._write_strip("unset FFLAGS")
                self._write_strip("unset CFFLAGS")
                self._write_strip("unset LDFLAGS")
                self._write_strip('export ASFLAGS="${ASFLAGS}${ASFLAGS:+ }--32"')
                self._write_strip('export CFLAGS="-O2 -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export CXXFLAGS="-O2 -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export FCFLAGS="-O2 -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export FFLAGS="-O2 -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export CFFLAGS="-O2 -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export LDFLAGS="-O2 -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
            else:
                self._write_strip("export AR=gcc-ar")
                self._write_strip("export RANLIB=gcc-ranlib")
                self._write_strip("export NM=gcc-nm")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                self._write_strip("unset CPATH")
                self._write_strip('export PKG_CONFIG_PATH="/usr/lib32/pkgconfig:/usr/share/pkgconfig"')
                self._write_strip("unset ASFLAGS")
                self._write_strip("unset CFLAGS")
                self._write_strip("unset CXXFLAGS")
                self._write_strip("unset FCFLAGS")
                self._write_strip("unset FFLAGS")
                self._write_strip("unset CFFLAGS")
                self._write_strip("unset LDFLAGS")
                self._write_strip('export ASFLAGS="${ASFLAGS}${ASFLAGS:+ }--32"')
                self._write_strip('export CFLAGS="-O2 -ffat-lto-objects -fuse-linker-plugin -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export CXXFLAGS="-O2 -ffat-lto-objects -fuse-linker-plugin -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export FCFLAGS="-O2 -ffat-lto-objects -fuse-linker-plugin -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export FFLAGS="-O2 -ffat-lto-objects -fuse-linker-plugin -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export CFFLAGS="-O2 -ffat-lto-objects -fuse-linker-plugin -fvisibility-inlines-hidden -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')
                self._write_strip('export LDFLAGS="-O2 -ffat-lto-objects -fuse-linker-plugin -pipe -fPIC -march=native -mtune=native -m32 -mstackrealign"')

    def write_variables(self):
        """Write variable exports to spec file."""
        flagsalt1c = []
        flagsalt1cxx = []
        flagsalt1ldflags = []
        flags = []
        arch = os.uname()[4]

        # Clear ships with a patch in GCC that allows ignoring the -Werror
        # compilation flag if this environment variable is set.  -Werror
        # is a useful flag for the upstream package maintainers, but is
        # a source of headaches for downstream users.
        self._write_strip("export GCC_IGNORE_WERROR=1\n")

        if self.config.config_opts["use_clang"]:
            self._write_strip("export CC=clang\n")
            self._write_strip("export CXX=clang++\n")
            # self._write_strip("CFLAGS=${CFLAGS/ -Wa,/ -fno-integrated-as -Wa,}")
            # self._write_strip
            lto = "-flto=auto"
        else:
            lto = "-flto=16"

        if not self.config.set_gopath:
            self._write_strip("export GOPROXY=file:///usr/share/goproxy")

        if self.config.config_opts["optimize_size"]:
            if self.config.config_opts["use_clang"]:
                flags.extend(["-Os", "-ffunction-sections", "-fdata-sections"])
            else:
                flags.extend(["-Os", "-ffunction-sections", "-fdata-sections", "-fno-semantic-interposition"])
        if self.config.config_opts["security_sensitive"]:
            flags.append("-fstack-protector-strong")
            if arch == 'x86_64':
                flags.append("-fzero-call-used-regs=used")
        if self.need_avx2_flags:
            flags.extend(["-O3", "-march=native -mtune=native"])
        if self.need_avx512_flags:
            flags.extend(["-O3", "-march=skylake-avx512"])
        if self.config.config_opts["insecure_build"]:
            self._write_strip('export CFLAGS="-O3 -g -fopt-info-vec "\n')
            self._write_strip("unset LDFLAGS\n")
        if self.config.config_opts["conservative_flags"]:
            self._write_strip(
                'export CFLAGS="-O2 -g -Wp,-D_FORTIFY_SOURCE=2 '
                "-fexceptions -fstack-protector "
                "--param=ssp-buffer-size=32 -Wformat "
                "-Wformat-security -Wno-error "
                "-Wl,-z,max-page-size=0x1000 "
                '-march=native -mtune=native"\n'
            )
            self._write_strip("export CXXFLAGS=$CFLAGS\n")
            self._write_strip(
                'export FFLAGS="-O2 -g -Wp,-D_FORTIFY_SOURCE=2 '
                "-fexceptions -fstack-protector "
                "--param=ssp-buffer-size=32 "
                "-Wno-error "
                "-Wl,-z,max-page-size=0x1000 "
                '-march=native -mtune=native"\n'
            )
            self._write_strip("export FCFLAGS=$FFLAGS\n")
            self._write_strip("unset LDFLAGS\n")
        if self.config.config_opts["use_clang"]:
            self._write_strip("unset LDFLAGS\n")
        if self.config.config_opts["funroll-loops"]:
            if self.config.config_opts["use_clang"]:
                flags.extend(["-O3"])
            else:
                flags.extend(["-Ofast", "-fno-semantic-interposition", "-falign-functions=32", "-mprefer-vector-width=256"])
        if self.config.default_pattern != 'qmake':
            if self.config.config_opts['use_lto']:
                flags.extend(["-O3", lto, "-ffat-lto-objects"])
                if self.config.config_opts["use_clang"]:
                    self._write_strip("export AR=llvm-ar\n")
                    self._write_strip("export RANLIB=llvm-ranlib\n")
                    self._write_strip("export NM=llvm-nm\n")
                else:
                    self._write_strip("export AR=gcc-ar\n")
                    self._write_strip("export RANLIB=gcc-ranlib\n")
                    self._write_strip("export NM=gcc-nm\n")
            else:
                flags.extend(["-fno-lto"])
        if self.config.config_opts["fast-math"]:
            flags.extend(["-ffast-math", "-ftree-loop-vectorize"])
        if self.config.config_opts["pgo"]:
            flags.extend(["-O3"])
        if self.content.gcov_file:
            flags = list(filter((lto).__ne__, flags))
            flags.extend(["-O3", "-fauto-profile=%{{SOURCE{0}}}".format(self.source_index[self.config.sources["gcov"][0]])])
        if (flags or self.config.config_opts["broken_c++"]) and not self.config.config_opts["fsalt1"] and not self.config.config_opts["altflags_pgo"]:
            flags = sorted(list(set(flags)))
            self._write_strip('export CFLAGS="$CFLAGS {0} "\n'.format(" ".join(flags)))
            self._write_strip('export FCFLAGS="$FFLAGS {0} "\n'.format(" ".join(flags)))
            self._write_strip('export FFLAGS="$FFLAGS {0} "\n'.format(" ".join(flags)))
            # leave the export CXXFLAGS line open in case
            self._write('export CXXFLAGS="$CXXFLAGS {0} '.format(" ".join(flags)))
            if self.config.config_opts["broken_c++"]:
                self._write("-std=gnu++98")
            # close the open quote from CXXFLAGS export and add newline
            self._write('"\n')

        if (
            self.config.profile_payload
            and self.config.profile_payload[0]
            and not self.need_avx2_flags
            and not self.need_avx512_flags
            and not self.config.config_opts["fsalt1"]
            and not self.config.config_opts["altflags_pgo"]
        ):
            genflags = []
            useflags = []
            genflags.extend(
                ["-fprofile-generate", "-fprofile-dir=/var/tmp/pgo", "-fprofile-update=atomic", "-fprofile-abs-path", "-fprofile-arcs", "-ftest-coverage", "--coverage", "-fprofile-partial-training"]
            )
            useflags.extend(["-fprofile-use", "-fprofile-dir=/var/tmp/pgo", "-fprofile-correction", "-fprofile-partial-training"])

            self._write_strip('export CFLAGS_GENERATE="$CFLAGS {0} "\n'.format(" ".join(genflags)))
            self._write_strip('export FCFLAGS_GENERATE="$FCFLAGS {0} "\n'.format(" ".join(genflags)))
            self._write_strip('export FFLAGS_GENERATE="$FFLAGS {0} "\n'.format(" ".join(genflags)))
            self._write_strip('export CXXFLAGS_GENERATE="$CXXFLAGS {0} "\n'.format(" ".join(genflags)))
            self._write_strip('export LDFLAGS_GENERATE="$LDFLAGS {0} "\n'.format(" ".join(genflags)))

            self._write_strip('export CFLAGS_USE="$CFLAGS {0} "\n'.format(" ".join(useflags)))
            self._write_strip('export FCFLAGS_USE="$FCFLAGS {0} "\n'.format(" ".join(useflags)))
            self._write_strip('export FFLAGS_USE="$FFLAGS {0} "\n'.format(" ".join(useflags)))
            self._write_strip('export CXXFLAGS_USE="$CXXFLAGS {0} "\n'.format(" ".join(useflags)))
            self._write_strip('export LDFLAGS_USE="$LDFLAGS {0} "\n'.format(" ".join(useflags)))
            self._write_strip("##")

        if self.config.config_opts["fsalt1"] and not self.config.config_opts["altflags_pgo"]:
            if self.config.altflags1f and self.config.altflags1f[0]:
                self._write_strip("## altflags1f content")
                for line in self.config.altflags1f:
                    self._write("{}\n".format(line))
                self._write_strip("## altflags1f end")
            elif self.config.altflags1 and self.config.altflags1[0]:
                self._write_strip("## altflags1 content")
                for line in self.config.altflags1:
                    self._write("{}\n".format(line))
                self._write_strip("## altflags1 end")
            else:
                flagsalt1c.extend(
                    [
                        "-g",
                        "-feliminate-unused-debug-types",
                        "-pipe",
                        "-Wall",
                        "-Wl,--hash-style=gnu",
                        "-Wp,-D_REENTRANT",
                        "-Wl,-sort-common",
                        "-Wl,--enable-new-dtags",
                        "-fasynchronous-unwind-tables",
                        "-falign-functions=32",
                        "-fno-math-errno",
                        "-ftree-loop-distribute-patterns",
                        "-Wl,-O2",
                        "-Wl,-z,now",
                        "-Wl,-z,relro",
                        "-fno-semantic-interposition",
                        "-fno-trapping-math",
                        "-m64",
                        "-ffat-lto-objects",
                        "-fuse-linker-plugin",
                        "-flto=12",
                        "-mtune=native",
                        "-march=native",
                        "-fipa-pta",
                        "-fdevirtualize-at-ltrans",
                        "-fno-plt",
                        "-fno-pie",
                        "-fno-PIE",
                        "-fno-PIC",
                        "-fpic",
                        "-fuse-ld=bfd",
                        "-fno-stack-protector",
                        "-O3",
                        "-floop-nest-optimize",
                        "-Wl,--build-id=sha1",
                        "-Wno-error",
                        "-ftree-loop-distribute-patterns",
                        "-ftree-vectorize",
                        "-ftree-loop-vectorize",
                        "-malign-data=cacheline",
                        "-fasynchronous-unwind-tables",
                        "-Wl,--as-needed",
                        "-funroll-loops",
                        "-fno-stack-protector",
                        "-mtls-dialect=gnu2",
                    ]
                )
                flagsalt1cxx.extend(
                    [
                        "-g",
                        "-feliminate-unused-debug-types",
                        "-pipe",
                        "-Wall",
                        "-Wl,--hash-style=gnu",
                        "-Wp,-D_REENTRANT",
                        "-Wl,-sort-common",
                        "-Wl,--enable-new-dtags",
                        "-fasynchronous-unwind-tables",
                        "-falign-functions=32",
                        "-fno-math-errno",
                        "-ftree-loop-distribute-patterns",
                        "-Wl,-O2",
                        "-Wl,-z,now",
                        "-Wl,-z,relro",
                        "-fno-semantic-interposition",
                        "-fno-trapping-math",
                        "-m64",
                        "-ffat-lto-objects",
                        "-fuse-linker-plugin",
                        "-flto=12",
                        "-mtune=native",
                        "-march=native",
                        "-fipa-pta",
                        "-fdevirtualize-at-ltrans",
                        "-fno-plt",
                        "-fvisibility-inlines-hidden",
                        "-Wl,--enable-new-dtags",
                        "-fno-pie",
                        "-fno-PIE",
                        "-fno-PIC",
                        "-fpic",
                        "-fuse-ld=bfd",
                        "-fno-stack-protector",
                        "-O3",
                        "-floop-nest-optimize",
                        "-Wl,--build-id=sha1",
                        "-Wno-error",
                        "-ftree-loop-distribute-patterns",
                        "-ftree-vectorize",
                        "-ftree-loop-vectorize",
                        "-malign-data=cacheline",
                        "-fasynchronous-unwind-tables",
                        "-Wl,--as-needed",
                        "-funroll-loops",
                        "-fno-stack-protector",
                        "-mtls-dialect=gnu2",
                    ]
                )
                flagsalt1ldflags.extend(
                    [
                        "-Wl,-sort-common",
                        "-fipa-pta",
                        "-fdevirtualize-at-ltrans",
                        "-fno-semantic-interposition",
                        "-fno-plt",
                        "-Wl,--hash-style=gnu",
                        "-flto=12",
                        "-fuse-linker-plugin",
                        "-ffat-lto-objects",
                        "-mtune=native",
                        "-march=native",
                        "-fno-pie",
                        "-fno-PIE",
                        "-fno-PIC",
                        "-fpic",
                        "-fuse-ld=bfd",
                        "-fno-stack-protector",
                        "-Wl,-O2",
                        "-Wl,-z,now",
                        "-Wl,-z,relro",
                        "-O3",
                        "-floop-nest-optimize",
                        "-Wl,--build-id=sha1",
                        "-ftree-loop-distribute-patterns",
                        "-ftree-vectorize",
                        "-ftree-loop-vectorize",
                        "-malign-data=cacheline",
                        "-fasynchronous-unwind-tables",
                        "-Wl,--as-needed",
                        "-funroll-loops",
                        "-fno-stack-protector",
                        "-mtls-dialect=gnu2",
                    ]
                )
                flagsalt1c = sorted(list(set(flagsalt1c)))
                flagsalt1cxx = sorted(list(set(flagsalt1cxx)))
                flagsalt1ldflags = sorted(list(set(flagsalt1ldflags)))
                self._write_strip('export CFLAGS="{0} "\n'.format(" ".join(flagsalt1c)))
                self._write_strip('export FCFLAGS="{0} "\n'.format(" ".join(flagsalt1c)))
                self._write_strip('export FFLAGS="{0} "\n'.format(" ".join(flagsalt1c)))
                self._write_strip('export CFFLAGS="{0} "\n'.format(" ".join(flagsalt1c)))
                self._write_strip('export LDFLAGS="{0} "\n'.format(" ".join(flagsalt1ldflags)))
                # leave the export CXXFLAGS line open in case
                self._write('export CXXFLAGS="{0} '.format(" ".join(flagsalt1cxx)))
                if self.config.config_opts["broken_c++"]:
                    self._write("-std=gnu++98")
                # close the open quote from CXXFLAGS export and add newline
                self._write('"\n')
        if self.config.profile_payload and self.config.profile_payload[0] and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
            genflags = []
            useflags = []
            genflags.extend(
                ["-fprofile-generate", "-fprofile-dir=/var/tmp/pgo", "-fprofile-update=atomic", "-fprofile-abs-path", "-fprofile-arcs", "-ftest-coverage", "--coverage", "-fprofile-partial-training"]
            )
            useflags.extend(["-fprofile-use", "-fprofile-dir=/var/tmp/pgo", "-fprofile-correction", "-fprofile-partial-training"])
            if self.config.altflags_pgof and self.config.altflags_pgof[0]:
                self._write_strip("## altflags_pgof content")
                for line in self.config.altflags_pgof:
                    self._write("{}\n".format(line))
                self._write_strip("## altflags_pgof end")
            elif self.config.altflags_pgo and self.config.altflags_pgo[0]:
                self._write_strip("## altflags_pgo content")
                for line in self.config.altflags_pgo:
                    self._write("{}\n".format(line))
                self._write_strip("## altflags_pgo end")
            else:
                self._write_strip("## altflags_pgo content")
                self._write_strip("## pgo generate")
                self._write_strip('export CFLAGS_GENERATE="$CFLAGS {0} "\n'.format(" ".join(genflags)))
                self._write_strip('export FCFLAGS_GENERATE="$FCFLAGS {0} "\n'.format(" ".join(genflags)))
                self._write_strip('export FFLAGS_GENERATE="$FFLAGS {0} "\n'.format(" ".join(genflags)))
                self._write_strip('export CXXFLAGS_GENERATE="$CXXFLAGS {0} "\n'.format(" ".join(genflags)))
                self._write_strip('export LDFLAGS_GENERATE="$LDFLAGS {0} "\n'.format(" ".join(genflags)))
                self._write_strip("## pgo use")
                self._write_strip('export CFLAGS_USE="$CFLAGS {0} "\n'.format(" ".join(useflags)))
                self._write_strip('export FCFLAGS_USE="$FCFLAGS {0} "\n'.format(" ".join(useflags)))
                self._write_strip('export FFLAGS_USE="$FFLAGS {0} "\n'.format(" ".join(useflags)))
                self._write_strip('export CXXFLAGS_USE="$CXXFLAGS {0} "\n'.format(" ".join(useflags)))
                self._write_strip('export LDFLAGS_USE="$LDFLAGS {0} "\n'.format(" ".join(useflags)))
                self._write_strip("## altflags_pgo end")

    def write_check(self):
        """Write check section to spec file."""
        if self.tests_config and not self.config.config_opts["skip_tests"]:
            self._write_strip("%check")
            self._write_strip("export LANG=C.UTF-8")
            self.write_proxy_exports()
            self._write_strip(self.tests_config)
            self._write_strip("\n")

    def write_license_files(self):
        """Install all license files for this package."""
        if len(self.license_files) > 0:
            self._write_strip("mkdir -p %{buildroot}/usr/share/package-licenses/" + self.name)
            for file in self.license_files:
                file2 = self.hashes[file]
                # Use the absolute path to the source license file b/c we don't know for sure where we are
                self._write_strip("cp " + "%{_builddir}/" + file + " %{buildroot}/usr/share/package-licenses/" + self.name + "/" + file2 + "\n")

    def write_profile_payload_content(self, pattern=None, build_type=None):
        if build_type == None:
            self._write_strip("## profile_payload start")
            self._write_strip("unset LD_LIBRARY_PATH")
            self._write_strip("unset LIBRARY_PATH")
            for line in self.config.profile_payload:
                self._write("{}\n".format(line))
            self._write_strip('export LD_LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
            self._write_strip('export LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
            self._write_strip("## profile_payload end")
        elif build_type == "special":
            if self.config.profile_payload_special:
                self._write_strip("## profile_payload_special start")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                for line in self.config.profile_payload_special:
                    self._write("{}\n".format(line))
                self._write_strip('export LD_LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip('export LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip("## profile_payload_special end")
            else:
                self._write_strip("## profile_payload start")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                for line in self.config.profile_payload:
                    self._write("{}\n".format(line))
                self._write_strip('export LD_LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip('export LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip("## profile_payload end")
        elif build_type == "special2":
            if self.config.profile_payload_special2:
                self._write_strip("## profile_payload_special2 start")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                for line in self.config.profile_payload_special2:
                    self._write("{}\n".format(line))
                self._write_strip('export LD_LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip('export LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip("## profile_payload_special2 end")
            else:
                self._write_strip("## profile_payload start")
                self._write_strip("unset LD_LIBRARY_PATH")
                self._write_strip("unset LIBRARY_PATH")
                for line in self.config.profile_payload:
                    self._write("{}\n".format(line))
                self._write_strip('export LD_LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip('export LIBRARY_PATH="/usr/nvidia/lib64:/usr/nvidia/lib64/vdpau:/usr/nvidia/lib64/xorg/modules/drivers:/usr/nvidia/lib64/xorg/modules/extensions:/usr/local/cuda/lib64:/usr/lib64/haswell:/usr/lib64/haswell/pulseaudio:/usr/lib64/haswell/alsa-lib:/usr/lib64/haswell/gstreamer-1.0:/usr/lib64/haswell/pipewire-0.3:/usr/lib64/haswell/spa-0.2:/usr/lib64/dri:/usr/lib64/chromium:/usr/lib64:/usr/lib64/pulseaudio:/usr/lib64/alsa-lib:/usr/lib64/gstreamer-1.0:/usr/lib64/pipewire-0.3:/usr/lib64/spa-0.2:/usr/lib:/aot/intel/oneapi/compiler/latest/linux/compiler/lib/intel64_lin:/aot/intel/oneapi/compiler/latest/linux/lib:/aot/intel/oneapi/mkl/latest/lib/intel64:/aot/intel/oneapi/tbb/latest/lib/intel64/gcc4.8:/usr/share:/usr/lib64/wine:/usr/nvidia/lib32:/usr/nvidia/lib32/vdpau:/usr/lib32:/usr/lib32/wine"')
                self._write_strip("## profile_payload end")

    def write_profile_payload(self, pattern=None, build_type=None):
        """Write the profile_payload specified for this package."""
        if not self.config.profile_payload and not self.config.config_opts["altflags_pgo"] or self.config.config_opts["fsalt1"]:
            return
        use_subdir = True
        init = ""
        init2 = ""
        post = ""
        self._write_strip("if [ ! -f statuspgo ]; then")
        self._write_strip("echo PGO Phase 1")
        if pattern == "configure" and build_type == "special":
            if self.config.configure_macro_special:
                if use_subdir and self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                self._write_strip(f"{self.get_profile_generate_flags()}")
                self.write_build_append()
                for line in self.config.configure_macro_special:
                    self._write("{}\n".format(line))
            else:
                if use_subdir and self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                init = f"{self.get_profile_generate_flags()}"
                init2 = f"%configure {self.config.extra_configure_special}"
        elif pattern == "configure" and build_type == "special2":
            if self.config.configure_macro_special2:
                if use_subdir and self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                self._write_strip(f"{self.get_profile_generate_flags()}")
                self.write_build_append()
                for line in self.config.configure_macro_special2:
                    self._write("{}\n".format(line))
            else:
                if use_subdir and self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                init = f"{self.get_profile_generate_flags()}"
                init2 = f"%configure {self.config.extra_configure_special2}"
        elif pattern == "configure" and build_type is None:
            if self.config.configure_macro:
                if use_subdir and self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                self._write_strip(f"{self.get_profile_generate_flags()}")
                self.write_build_append()
                for line in self.config.configure_macro:
                    self._write("{}\n".format(line))
            else:
                if use_subdir and self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                init = f"{self.get_profile_generate_flags()}"
                init2 = f"%configure {self.config.extra_configure} {self.config.extra_configure64} "
        elif pattern == "configure_ac" and build_type == "special":
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            init2 = f"%reconfigure {self.config.extra_configure_special}"
        elif pattern == "configure_ac" and build_type == "special2":
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            init = f"%reconfigure {self.config.extra_configure_special2}"
        elif pattern == "configure_ac" and build_type is None:
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            init2 = f"%reconfigure {self.config.extra_configure} {self.config.extra_configure64}"
        elif pattern == "autogen" and build_type == "special":
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            init2 = f"%autogen {self.config.extra_configure_special}"
        elif pattern == "autogen" and build_type == "special2":
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            init2 = f"%autogen {self.config.extra_configure_special2}"
        elif pattern == "autogen" and build_type is None:
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            init2 = f"%autogen {self.config.extra_configure} {self.config.extra_configure64}"
        #elif pattern == "cmake":
            #use_subdir = False
            #init = f"{self.get_profile_generate_flags()} "
            #post = f"{self.get_profile_use_flags()} "
        elif pattern == "make":
            if use_subdir and self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            init = f"{self.get_profile_generate_flags()}"
            post = f"{self.get_profile_use_flags()} "

        if init:
            self._write_strip(init)
            self.write_build_append()
            if init2:
                self._write_strip(init2)

        self.write_make_line(build32=False, build_type=build_type, pgo=False, pattern=pattern)
        self._write_strip("\n")
        self.write_profile_payload_content(pattern=pattern, build_type=build_type)

        if self.config.custom_clean_pgo:
            self._write_strip("{}\n".format(self.config.custom_clean_pgo))
        else:
            self._write_strip("\nmake clean || :\n")
        self._write_strip("echo USED > statuspgo")
        self._write_strip("fi")
        self._write_strip("if [ -f statuspgo ]; then")
        self._write_strip("echo PGO Phase 2\n")

        if use_subdir and self.config.subdir:
            self._write_strip("popd")
        if post:
            self._write_strip(post)

    def write_make_install_buildtcl_script(self):
        """Write install section to spec file for buildtcl script builds."""
        self._write_strip("%install")
        # time.time() returns a float, but we only need second-precision
        self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self.write_license_files()

        if self.config.config_opts["32bit"]:
            if self.config.install_macro_32:
                self._write_strip("## install_macro_32 start")
                for line in self.config.install_macro_32:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_32 end")
            else:
                self._write("pushd ../build32/" + self.config.subdir)
                self._write("%buildtcl_script_install {} {}".format(self.config.extra_make_install, self.config.extra_make32_install))
                self._write("if [ -d  %{buildroot}/usr/lib32/pkgconfig ]")
                self._write("then")
                self._write("    pushd %{buildroot}/usr/lib32/pkgconfig\n")
                self._write("    for i in *.pc ; do ln -s $i 32$i ; done\n")
                self._write("    popd\n")
                self._write_strip("fi")
                self._write_strip("popd")

        if self.config.config_opts["build_special"]:
            if self.config.install_macro_build_special:
                self.write_install_prepend("special")
                self._write_strip("## install_macro_build_special start\n")
                for line in self.config.install_macro_build_special:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_build_special end\n")
            else:
                self.write_install_prepend("special")
                self._write_strip("pushd ../build-special/" + self.config.subdir)
                self._write_strip("%buildtcl_script_install {}\n".format(self.config.extra_make_install_special))
                self._write_strip("popd")

        if self.config.config_opts["build_special2"]:
            if self.config.install_macro_build_special2:
                self.write_install_prepend("special2")
                self._write_strip("## install_macro_build_special2 start")
                for line in self.config.install_macro_build_special2:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_build_special2 end")
            else:
                self.write_install_prepend("special2")
                self._write_strip("pushd ../build-special2/" + self.config.subdir)
                self._write_strip("%buildtcl_script_install {}\n".format(self.config.extra_make_install_special2))
                self._write_strip("popd")

        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)
        if self.config.install_macro:
            self._write_strip("## install_macro start")
            for line in self.config.install_macro:
                self._write("{}\n".format(line))
            self._write_strip("## install_macro end")
        else:
            self._write_strip("%buildtcl_script_install {}\n".format(self.config.extra_make_install))

        if self.config.subdir:
            self._write_strip("popd")
        self.write_find_lang()


    def write_make_install_buildtcl_configure(self):
        """Write install section to spec file for buildtcl configure builds."""
        self._write_strip("%install")
        # time.time() returns a float, but we only need second-precision
        self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self.write_license_files()

        if self.config.config_opts["32bit"]:
            if self.config.install_macro_32:
                self._write_strip("## install_macro_32 start")
                for line in self.config.install_macro_32:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_32 end")
            else:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self._write_strip("%buildtcl_configure_install {} {}".format(self.config.extra_make_install, self.config.extra_make32_install))
                self._write_strip("if [ -d  %{buildroot}/usr/lib32/pkgconfig ]")
                self._write_strip("then")
                self._write("    pushd %{buildroot}/usr/lib32/pkgconfig\n")
                self._write("    for i in *.pc ; do ln -s $i 32$i ; done\n")
                self._write("    popd\n")
                self._write_strip("fi")
                self._write_strip("popd")

        if self.config.config_opts["build_special"]:
            if self.config.install_macro_build_special:
                self.write_install_prepend("special")
                self._write_strip("## install_macro_build_special start\n")
                for line in self.config.install_macro_build_special:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_build_special end\n")
            else:
                self.write_install_prepend("special")
                self._write_strip("pushd ../build-special/" + self.config.subdir)
                self._write_strip("%buildtcl_configure_install {}\n".format(self.config.extra_make_install_special))
                self._write_strip("popd")

        if self.config.config_opts["build_special2"]:
            if self.config.install_macro_build_special2:
                self.write_install_prepend("special2")
                self._write_strip("## install_macro_build_special2 start")
                for line in self.config.install_macro_build_special2:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_build_special2 end")
            else:
                self.write_install_prepend("special2")
                self._write_strip("pushd ../build-special2/" + self.config.subdir)
                self._write_strip("%buildtcl_configure_install {}\n".format(self.config.extra_make_install_special2))
                self._write_strip("popd")

        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)
        if self.config.install_macro:
            self._write_strip("## install_macro start")
            for line in self.config.install_macro:
                self._write("{}\n".format(line))
            self._write_strip("## install_macro end")
        else:
            self._write_strip("%buildtcl_configure_install {}\n".format(self.config.extra_make_install))

        if self.config.subdir:
            self._write_strip("popd")
        self.write_find_lang()


    def write_make_install(self):
        """Write install section to spec file for make builds."""
        self._write_strip("%install")
        # time.time() returns a float, but we only need second-precision
        self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self.write_license_files()

        if self.config.config_opts["32bit"]:
            if self.config.install_macro_32:
                self._write_strip("## install_macro_32 start")
                for line in self.config.install_macro_32:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_32 end")
            else:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self._write_strip("%make_install32 {} {}".format(self.config.extra_make_install, self.config.extra_make32_install))
                self._write_strip("if [ -d  %{buildroot}/usr/lib32/pkgconfig ]")
                self._write_strip("then")
                self._write("    pushd %{buildroot}/usr/lib32/pkgconfig\n")
                self._write("    for i in *.pc ; do ln -s $i 32$i ; done\n")
                self._write("    popd\n")
                self._write_strip("fi")
                self._write_strip("popd")
                self._write_strip("if [ -d %{buildroot}/usr/share/pkgconfig ]")
                self._write_strip("then")
                self._write_strip("    pushd %{buildroot}/usr/share/pkgconfig")
                self._write_strip("    for i in *.pc ; do ln -s $i 32$i ; done")
                self._write_strip("    popd")
                self._write_strip("fi")
                self._write_strip("popd")
            if self.config.config_opts["build_special_32"]:
                if self.config.install_macro_build_special_32:
                    self._write_strip("## install_macro_build_special_32 start")
                    for line in self.config.install_macro_build_special_32:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_build_special_32 end")
                else:
                    self._write_strip("pushd ../build-special-32/" + self.config.subdir)
                    if self.config.extra_make_install_special_32:
                        self._write_strip("%make_install32 {} {}".format(self.config.extra_make_install, self.config.extra_make_install_special_32))
                    else:
                        self._write_strip("%make_install32 {} {}".format(self.config.extra_make_install, self.config.extra_make32_install))
                    self._write_strip("if [ -d  %{buildroot}/usr/lib32/pkgconfig ]")
                    self._write_strip("then")
                    self._write("    pushd %{buildroot}/usr/lib32/pkgconfig\n")
                    self._write("    for i in *.pc ; do ln -s $i 32$i || :; done\n")
                    self._write("    popd\n")
                    self._write_strip("fi")
                    self._write_strip("popd")
        if not self.config.config_opts["32bit_only"]:
            if self.config.config_opts["use_avx512"]:
                if self.config.install_macro_512:
                    self._write_strip("## install_macro_512 start")
                    for line in self.config.install_macro_512:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_512 end")
                else:
                    self._write_strip("pushd ../buildavx512/" + self.config.subdir)
                    self._write_strip("%make_install_avx512 {}\n".format(self.config.extra_make_install))
                    self._write_strip("popd")

            if self.config.config_opts["use_avx2"]:
                if self.config.install_macro_avx2:
                    self._write_strip("## install_macro_avx2 start")
                    for line in self.config.install_macro_avx2:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_avx2 end")
                else:
                    self._write_strip("pushd ../buildavx2/" + self.config.subdir)
                    self._write_strip("%make_install_avx2 {}\n".format(self.config.extra_make_install))
                    self._write_strip("popd")

            if self.config.config_opts["openmpi"]:
                if self.config.install_macro_openmpi:
                    self._write("## install_macro_openmpi start")
                    for line in self.config.install_macro_openmpi:
                        self._write("{}\n".format(line))
                    self._write("## install_macro_openmpi end")
                else:
                    self._write_strip("pushd ../build-openmpi/" + self.config.subdir)
                    self.write_install_openmpi()
                    self._write_strip("popd")

            if self.config.config_opts["build_special"]:
                if self.config.install_macro_build_special:
                    self.write_install_prepend("special")
                    self._write("## install_macro_build_special start\n")
                    for line in self.config.install_macro_build_special:
                        self._write("{}\n".format(line))
                    self._write("## install_macro_build_special end\n")
                else:
                    self.write_install_prepend("special")
                    self._write_strip("pushd ../build-special/" + self.config.subdir)
                    self._write_strip("%make_install_special {}\n".format(self.config.extra_make_install_special))
                    self._write_strip("popd")

            if self.config.config_opts["build_special2"]:
                if self.config.install_macro_build_special2:
                    self.write_install_prepend("special2")
                    self._write_strip("## install_macro_build_special2 start")
                    for line in self.config.install_macro_build_special2:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_build_special2 end")
                else:
                    self.write_install_prepend("special2")
                    self._write_strip("pushd ../build-special2/" + self.config.subdir)
                    self._write_strip("%make_install_special2 {}\n".format(self.config.extra_make_install_special2))
                    self._write_strip("popd")

            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            if self.config.install_macro:
                self._write_strip("## install_macro start")
                for line in self.config.install_macro:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro end")
            else:
                self._write_strip("%make_install {}\n".format(self.config.extra_make_install))

            if self.config.subdir:
                self._write_strip("popd")
        self.write_find_lang()

    def write_mvnbin_install(self):
        """Write out installation for mvnbin content."""
        self.write_license_files()

        patterns = [
            re.compile(r"maven.*org/maven2/([a-zA-Z\-\_]+)/([a-zA-Z\-\_]+)/([a-zA-Z-\_\d.]+)/[a-zA-Z-\_\d.]*\.(?:pom|jar|xml|signature)"),
            re.compile(r"maven.apache.org/maven2/([a-zA-Z\-\_]+)/([a-zA-Z\-\_]+)/([\d.]+)/[a-z-\_.\d]*\.(?:pom|jar|xml|signature)"),
            re.compile(r"maven.*org/maven2/([a-zA-Z-\_.\d/]+)/([a-zA-Z-\_.\d]*)/([a-zA-Z\d\.\_\-]+)/(?:[a-zA-Z-\_.\d]*)\.(?:pom|jar|xml|signature)"),
            re.compile(r"repository.mapr.com/maven/([a-zA-Z\-\_/]+)/([a-zA-Z\-\_]+)/([a-zA-Z-\_\d.]+)/[a-zA-Z-\_\d.]*\.(?:pom|jar|xml|signature)"),
            re.compile(r"packages.confluent.io/maven/([a-zA-Z\-\_/]+)/([a-zA-Z\-\_]+)/([a-zA-Z-\_\d.]+)/[a-zA-Z-\_\d.]*\.(?:pom|jar|xml|signature)"),
            re.compile(r"gradle.org/gradle/libs-releases/([a-zA-Z-\_.\d/]+)/([a-zA-Z-\_.\d]*)/([a-zA-Z\d\.\_\-]+)/(?:[a-zA-Z-\_.\d]*)\.(?:pom|jar)"),
            re.compile(r"gradle.org/m2/([a-zA-Z-\_.\d/]+)/([a-zA-Z-\_.\d]*)/([a-zA-Z\d\.\_\-]+)/(?:[a-zA-Z-\_.\d]*)\.(?:pom|jar)"),
        ]
        mvn_sources = [self.url] + sorted(self.config.sources["archive"])
        src_num = 0

        for src in mvn_sources:
            for pat in patterns:
                m = pat.search(src)
                if m:
                    groupid = m.group(1)
                    artifactid = m.group(2)
                    version = m.group(3)
                    src_dir = "{}/{}/{}".format(groupid, artifactid, version)
                    src_file = os.path.basename(src)
                    if src_file.endswith(".xml"):
                        src_file = "maven-metadata-central.xml"

                    self._write_strip("mkdir -p %{{buildroot}}/usr/share/java/.m2/repository/{}".format(src_dir))
                    self._write_strip("cp %{{SOURCE{}}} %{{buildroot}}/usr/share/java/.m2/repository/{}/{}".format(src_num, src_dir, src_file))
                    self._write_strip("\n")
                    break
            src_num += 1

    def write_maven_install(self):
        """Write installation steps to specfile for maven source packages."""
        self.write_license_files()

        # Iterate over all built versions
        for prefix in self.build_dirs.values():
            self._write_strip("cd ../{}\n".format(prefix))

            # Iterate over all target subdirs
            self._write_strip("for targetdir in $(find . -type d -name target); do")
            self._write_strip("pushd $targetdir")

            # Figure out the artifact details and path components
            # Find group ID; inherit from parent if necessary
            self._write_strip("export GROUP_PATH=$(xml sel -T -t -m '//_:project' --if 'boolean(_:groupId)' -v '_:groupId' --else -v '_:parent/_:groupId' ../pom.xml | sed 's#\\.#/#g')")
            # Find artifact name -- this should not be inherited
            self._write_strip("export ARTIFACT_ID=$(xml sel -T -t -m '//_:project' -v '_:artifactId' ../pom.xml)")
            # Find version -- this *might* be inherited from parent
            self._write_strip("export VERSION=$(xml sel -T -t -m '//_:project' --if 'boolean(_:version)' -v '_:version' --else -v '_:parent/_:version' ../pom.xml)")

            # Create the installation path
            self._write_strip("export DEPLOY_PATH=%{buildroot}/usr/share/java/.m2/repository/${GROUP_PATH}/${ARTIFACT_ID}/${VERSION}")
            self._write_strip("mkdir -p ${DEPLOY_PATH}")

            # We're going to be globbing for things that may not exist
            self._write_strip("shopt -s nullglob")

            # Copy all the jar files
            self._write_strip("for jarfile in ${ARTIFACT_ID}*.jar; do")
            self._write_strip('cp -p "${jarfile}" ${DEPLOY_PATH}/')
            self._write_strip("done")
            # Except this one -- it's redundant with the source tarball
            self._write_strip("rm -f ${DEPLOY_PATH}/${ARTIFACT_ID}-${VERSION}-sources.jar")

            # Install the POM file
            self._write_strip("cp -p ../pom.xml ${DEPLOY_PATH}/${ARTIFACT_ID}-${VERSION}.pom")

            # Next
            self._write_strip("popd")

            # All done
            self._write_strip("done")

    def write_gradle_install(self):
        """Write installation steps to specfile for gradle source packages."""
        self.write_license_files()

        # Iterate over all built versions
        for prefix in self.build_dirs.values():
            self._write_strip("cd ../{}\n".format(prefix))

            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)

            # User must provide the install goal in make_install_args
            self._write_strip("gradle --offline " + self.config.extra_make_install)

            # Install from a build/install directory, if it was created
            self._write_strip("if [[ -d build/install ]]; then")

            # Enter the installation subdir, so we can touch up what gets installed
            self._write_strip("pushd build/install")

            # Handle jarfiles in lib dir
            # The install goal results in packaging not only the jars that were
            # built, but also runtime deps that came from other packages. For every
            # jar we find in the installed directory, we'll check whether there's a
            # matching jar in the M2 repository provided by installed build deps.
            # If so, we'll replace this copy with a symlink.
            # TODO: call add_requires() with an appropriately-derived value so the
            # symlink will be resolved at chroot creation.
            self._write_strip("shopt -s nullglob")
            self._write_strip("for lib_dir in */lib; do")
            self._write_strip("pushd ${lib_dir}")
            self._write_strip("for jarfile in *.jar; do")
            self._write_strip("JARNAME=$(basename ${jarfile})")
            self._write_strip('REALJAR=$(find /usr/share/java/.m2/repository -type f -name "${JARNAME}")')
            self._write_strip("if ! [[ -z ${REALJAR} ]]; then")
            self._write_strip(r"ln -sf ${REALJAR/#\/usr\/share\/java/..\/..}")
            self._write_strip("fi")
            self._write_strip("done")
            self._write_strip("popd")
            self._write_strip("done")

            # Install the contents under main java path
            self._write_strip("mkdir -p %{buildroot}/usr/share/java/" + self.name)
            self._write_strip("cp -r lib %{buildroot}/usr/share/java/" + self.name)

            # Leave the build subdir
            self._write_strip("popd")

            # Done processing build/install directory
            self._write_strip("fi")

            if self.config.subdir:
                self._write_strip("popd")

    def write_prep_prepend(self):
        """Write out any custom supplied commands at the start of the %prep section."""
        if self.config.prep_prepend:
            self._write_strip("## prep_prepend content")
            for line in self.config.prep_prepend:
                self._write("{}\n".format(line))
            self._write_strip("## prep_prepend end")

    def write_build_prepend(self):
        """Write out any custom supplied commands at the start of the %build section."""
        if self.config.build_prepend:
            self._write_strip("## build_prepend content")
            for line in self.config.build_prepend:
                self._write("{}\n".format(line))
            self._write_strip("## build_prepend end")

    def write_build_prepend32(self):
        """Write out any custom supplied commands at the start of the %build section."""
        if self.config.build_prepend32:
            self._write_strip("## build_prepend32 content")
            for line in self.config.build_prepend32:
                self._write("{}\n".format(line))
            self._write_strip("## build_prepend32 end")

    def write_trystatic(self):
        """Write out trystatic command line."""
        if self.config.trystatic:
            self._write_strip("## trystatic content")
            for line in self.config.trystatic:
                self._write("{}\n".format(line))
            self._write_strip("## trystatic end")

    def write_make_prepend(self, build32=False):
        """Write out any custom supplied commands at the start of the meson/scons make section."""
        if build32 is False:
            if self.config.make_prepend:
                self._write_strip("## make_prepend content")
                for line in self.config.make_prepend:
                    self._write("{}\n".format(line))
                self._write_strip("## make_prepend end")
            if self.config.make_prepend64:
                self._write_strip("## make_prepend64 content")
                for line in self.config.make_prepend64:
                    self._write("{}\n".format(line))
                self._write_strip("## make_prepend64 end")
        if build32 is True:
            if self.config.make_prepend32:
                self._write_strip("## make_prepend32 content")
                for line in self.config.make_prepend32:
                    self._write("{}\n".format(line))
                self._write_strip("## make_prepend32 end")

    def write_build_append(self):
        """Write out any custom supplied commands at the end of the %build section."""
        if self.config.build_append:
            self._write_strip("## build_append content")
            for line in self.config.build_append:
                self._write("{}\n".format(line))
            self._write_strip("## build_append end\n")

    def write_install_prepend(self, build_type=None):
        """Write out any custom supplied commands at the start of the %install section."""
        if self.config.install_prepend and build_type is None:
            self._write_strip("## install_prepend content")
            for line in self.config.install_prepend:
                self._write("{}\n".format(line))
            self._write_strip("## install_prepend end")
        if self.config.install_prepend_special and build_type == "special":
            self._write_strip("## install_prepend_special content")
            for line in self.config.install_prepend_special:
                self._write("{}\n".format(line))
            self._write_strip("## install_prepend_special end")
        if self.config.install_prepend_special2 and build_type == "special2":
            self._write_strip("## install_prepend_special2 content")
            for line in self.config.install_prepend_special2:
                self._write("{}\n".format(line))
            self._write_strip("## install_prepend_special2 end")

    def write_install_append(self):
        """Write out any custom supplied commands at the very end of the %install section."""
        if self.config.install_append:
            self._write_strip("## install_append content")
            for line in self.config.install_append:
                self._write("{}\n".format(line))
            self._write_strip("## install_append end")
        if self.config.install_append_special and self.config.config_opts["build_special"]:
            self._write_strip("## install_append_special content")
            for line in self.config.install_append_special:
                self._write("{}\n".format(line))
            self._write_strip("## install_append_special end")
        if self.config.install_append_special2 and self.config.config_opts["build_special2"]:
            self._write_strip("## install_append_special2 content")
            for line in self.config.install_append_special2:
                self._write("{}\n".format(line))
            self._write_strip("## install_append_special2 end")
        if self.config.install_append_special_32 and self.config.config_opts["build_special_32"]:
            self._write_strip("## install_append_special_32 content")
            for line in self.config.install_append_special_32:
                self._write("{}\n".format(line))
            self._write_strip("## install_append_special_32 end")

    def write_cargo_assets(self):
        """Write out install assets found by filemanager.write_cargo_find_install_assets"""
        self._write_strip("## Cargo install assets")
        if self.cargo_install_assets:
            for i, install_cmd in enumerate(self.cargo_install_assets):
            #for (install_cmd1, install_cmd2) in self.cargo_install_assets:
                #self._write_strip(install_cmd1)
                #self._write_strip(install_cmd2)
                self._write_strip(install_cmd[0])
                self._write_strip(install_cmd[1])

    def write_exclude_deletes(self):
        """Write out deletes for excluded files."""
        if self.excludes:
            self._write_strip("## Remove excluded files")
        for exclude in self.excludes:
            self._write_strip(f"rm -f %{{buildroot}}{exclude}")

    def write_service_restart(self):
        """Enable configured units to be restarted with clr-service-restart."""
        if self.config.service_restart:
            self._write_strip("## service_restart content")
            installdir = "%{buildroot}/usr/share/clr-service-restart"
            self._write_strip("mkdir -p {}".format(installdir))
            for unit in self.config.service_restart:
                basename = os.path.basename(unit)
                self._write_strip("ln -s {} {}".format(unit, os.path.join(installdir, basename)))
            self._write_strip("## service_restart end")

    def write_source_installs(self):
        """Write out installs from SourceX lines."""
        if len(self.config.sources["unit"]) != 0:
            self._write_strip("mkdir -p %{buildroot}/usr/lib/systemd/system")
            for unit in self.config.sources["unit"]:
                self._write_strip("install -m 0644 %{{SOURCE{0}}} %{{buildroot}}/usr/lib/systemd/system/{1}".format(self.source_index[unit], unit))
        if len(self.config.sources["tmpfile"]) != 0:
            self._write_strip("mkdir -p %{buildroot}/usr/lib/tmpfiles.d")
            self._write_strip("install -m 0644 %{{SOURCE{0}}} %{{buildroot}}/usr/lib/tmpfiles.d/{1}.conf".format(self.source_index[self.config.sources["tmpfile"][0]], self.name))
        if len(self.config.sources["sysuser"]) != 0:
            self._write_strip("mkdir -p %{buildroot}/usr/lib/sysusers.d")
            self._write_strip("install -m 0644 %{{SOURCE{0}}} %{{buildroot}}/usr/lib/sysusers.d/{1}.conf".format(self.source_index[self.config.sources["sysuser"][0]], self.name))

        for source in self.config.extra_sources:
            if len(source) == 1:
                # Don't automatically install if we don't have install arguments
                continue
            actual_source = "%{_sourcedir}/" + source[0]
            dest = None
            install_args = []
            for arg in source[1].split():
                if dest is None and arg.startswith("/"):
                    dest = arg
                else:
                    install_args.append(arg)
            self._write_strip("mkdir -p %{{buildroot}}{0}".format(os.path.dirname(dest)))
            self._write_strip("install {0} {1} %{{buildroot}}{2}".format(" ".join(install_args), actual_source, dest))

    def write_cmake_install(self):
        """Write install section to spec file for cmake builds."""
        self.write_build_append()
        self._write_strip("%install")
        self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()

        self.write_license_files()

        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)

        if self.config.config_opts["32bit"]:
            if self.config.install_macro_32:
                self._write_strip("## install_macro_32 start")
                for line in self.config.install_macro_32:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro_32 end")
            else:
                self._write_strip("pushd clr-build32")
                if self.config.config_opts["use_ninja"]:
                    self._write_strip("%ninja_install32 {} {}".format(self.config.extra_make_install, self.config.extra_make32_install))
                else:
                    self._write_strip("%make_install32 {} {}".format(self.config.extra_make_install, self.config.extra_make32_install))
                self._write_strip("if [ -d  %{buildroot}/usr/lib32/pkgconfig ]")
                self._write_strip("then")
                self._write("    pushd %{buildroot}/usr/lib32/pkgconfig\n")
                self._write("    for i in *.pc ; do ln -s $i 32$i ; done\n")
                self._write("    popd\n")
                self._write_strip("fi")
                self._write_strip("popd")
                self._write_strip("if [ -d %{buildroot}/usr/share/pkgconfig ]")
                self._write_strip("then")
                self._write_strip("    pushd %{buildroot}/usr/share/pkgconfig")
                self._write_strip("    for i in *.pc ; do ln -s $i 32$i ; done")
                self._write_strip("    popd")
                self._write_strip("fi")
                self._write_strip("popd")
        if not self.config.config_opts["32bit_only"]:
            if self.config.config_opts["use_avx512"]:
                if self.config.install_macro_512:
                    self._write_strip("## install_macro_512 start")
                    for line in self.config.install_macro_512:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_512 end")
                else:
                    self._write_strip("pushd clr-build-avx512")
                    if self.config.config_opts["use_ninja"]:
                        self._write_strip("%ninja_install_avx512 {} || :\n".format(self.config.extra_make_install))
                    else:
                        self._write_strip("%make_install_avx512 {} || :\n".format(self.config.extra_make_install))
                    self._write_strip("popd")

            if self.config.config_opts["use_avx2"]:
                if self.config.install_macro_avx2:
                    self._write_strip("## install_macro_avx2 start")
                    for line in self.config.install_macro_avx2:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_avx2 end")
                else:
                    self._write_strip("pushd clr-build-avx2")
                    if self.config.config_opts["use_ninja"]:
                        self._write_strip("%ninja_install_avx2 {} || :\n".format(self.config.extra_make_install))
                    else:
                        self._write_strip("%make_install_avx2 {} || :\n".format(self.config.extra_make_install))
                    self._write_strip("popd")

            if self.config.config_opts["openmpi"]:
                if self.config.install_macro_openmpi:
                    self._write_strip("## install_macro_openmpi start")
                    for line in self.config.install_macro_openmpi:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_openmpi end")
                else:
                    self._write_strip("pushd clr-build-openmpi")
                    self.write_install_openmpi()
                    self._write_strip("popd")

            if self.config.config_opts["build_special"]:
                if self.config.install_macro_build_special:
                    self._write_strip("## install_macro_build_special start\n")
                    for line in self.config.install_macro_build_special:
                        self._write("{}\n".format(line))
                    self._write_strip("## install_macro_build_special end\n")
                else:
                    self._write_strip("pushd clr-build-special")
                    if self.config.config_opts["use_ninja"]:
                        self._write_strip("%ninja_install_special {} || :\n".format(self.config.extra_make_install_special))
                    else:
                        self._write_strip("%make_install_special {} || :\n".format(self.config.extra_make_install_special))
                    self._write_strip("popd")

            if self.config.install_macro:
                self._write_strip("## install_macro start")
                for line in self.config.install_macro:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro end")
            else:
                self._write_strip("pushd clr-build")
                if self.config.config_opts["use_ninja"]:
                    self._write_strip("%ninja_install {}\n".format(self.config.extra_make_install))
                else:
                    self._write_strip("%make_install {}\n".format(self.config.extra_make_install))
                self._write_strip("popd")

        if self.config.subdir:
            self._write_strip("popd")

        self.write_find_lang()

    def get_profile_generate_flags(self):
        """Return profile generate flags if proper configuration is set.

        If config.profile_payload is non-empty, returns
                'CFLAGS="${CFLAGS_GENERATE}" '
                'CXXFLAGS="${CXXFLAGS_GENERATE}" '
                'FFLAGS="${FFLAGS_GENERATE}" '
                'FCFLAGS="${FCFLAGS_GENERATE}" '
                'LDFLAGS="${LDFLAGS_GENERATE}" '

        otherwise an empty string is returned.
        """
        if self.config.profile_payload and self.config.profile_payload[0] and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
            return (
                'export CFLAGS="${CFLAGS_GENERATE}"\n'
                'export CXXFLAGS="${CXXFLAGS_GENERATE}"\n'
                'export FFLAGS="${FFLAGS_GENERATE}"\n'
                'export FCFLAGS="${FCFLAGS_GENERATE}"\n'
                'export LDFLAGS="${LDFLAGS_GENERATE}"\n'
                'export LIBS="${LIBS_GENERATE}"\n'
            )
        return ""

    def get_profile_use_flags(self):
        """Return profile generate flags if proper configuration is set.

        If config.profile_payload is non-empty, returns
                'CFLAGS="${CFLAGS_USE}" '
                'CXXFLAGS="${CXXFLAGS_USE}" '
                'FFLAGS="${FFLAGS_USE}" '
                'FCFLAGS="${FCFLAGS_USE}" '
                'LDFLAGS="${LDFLAGS_USE}" '

        otherwise an empty string is returned.
        """
        if self.config.profile_payload and self.config.profile_payload[0] and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
            return 'export CFLAGS="${CFLAGS_USE}"\n' 'export CXXFLAGS="${CXXFLAGS_USE}"\n' 'export FFLAGS="${FFLAGS_USE}"\n' 'export FCFLAGS="${FCFLAGS_USE}"\n' 'export LDFLAGS="${LDFLAGS_USE}"\n' 'unset LIBS\n'
        return ""

    def get_systemd_units(self):
        """Get systemd unit files from the files module."""
        service_file_section = "config"
        systemd_service_pattern = r"^/usr/lib/systemd/system/[^/]*\.(mount|service|socket|target)$"
        systemd_units = []

        if service_file_section not in self.packages:
            return systemd_units

        if service_file_section not in self.subpackages:
            return systemd_units

        for serv_f in self.packages[service_file_section]:
            if re.search(systemd_service_pattern, serv_f) and serv_f not in self.excludes:
                systemd_units.append(serv_f)

        for serv_f in self.subpackages[service_file_section]:
            if re.search(systemd_service_pattern, serv_f) and serv_f not in self.excludes:
                systemd_units.append(serv_f)

        return systemd_units

    def write_systemd_units(self):
        """Write out installs for systemd unit files."""
        units = self.get_systemd_units()
        for unit in units:
            self._write("systemctl --root=%{{buildroot}} enable {0}\n".format(os.path.basename(unit)))

    def write_buildtcl_script_pattern(self):
        """Write tcl build pattern to spec file."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_variables()
        if self.config.configure_macro:
            if self.config.subdir:
                self._write_strip("pushd {}".format(self.config.subdir))
            for line in self.config.configure_macro:
                self._write("{}\n".format(line))
            self.write_make_line()
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")
        else:
            if self.config.subdir:
                self._write_strip("pushd {}".format(self.config.subdir))
            self._write_strip("tclsh build.tcl {0} {1}".format(self.config.extra_configure, self.config.extra_configure64))
            self.write_make_line()
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")

        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/" + self.config.subdir)
            self.write_build_prepend()
            self.write_variables()
            self._write_strip("tclsh build.tcl {0}".format(self.config.extra_configure_special))
            self.write_make_line(build32=False, build_type="special", pgo=False, pattern=None)
            self._write_strip("popd")

        if self.config.config_opts["build_special2"]:
            self._write_strip("pushd ../build-special2/" + self.config.subdir)
            self.write_build_prepend()
            self.write_variables()
            self.write_profile_payload("configure", "special2")
            self._write_strip("tclsh build.tcl {0}".format(self.config.extra_configure_special2))
            self.write_make_line(build32=False, build_type="special2", pgo=False, pattern=None)
            self._write_strip("popd")

        if self.config.config_opts["32bit"]:
            if self.config.configure_macro_32:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self.write_build_prepend32()
                self.write_32bit_exports()
                self.write_build_append()
                self._write("{} ".format(self.config.configure_macro_32))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("popd")
            else:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self.write_build_prepend()
                self.write_32bit_exports()
                self.write_build_append()
                self._write_strip("tclsh build.tcl {0} {1}".format(self.config.extra_configure, self.config.extra_configure32))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("popd")
        self._write_strip("\n")
        self.write_check()
        self.write_make_install_buildtcl_script()

    def write_buildtcl_configure_pattern(self):
        """Write configure build tcl configure pattern to spec file."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_variables()
        if self.config.configure_macro:
            if self.config.subdir:
                self._write_strip("pushd {}".format(self.config.subdir))
            self._write("{} ".format(self.config.configure_macro))
            self.write_make_line()
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")
        else:
            if self.config.subdir:
                self._write_strip("pushd {}".format(self.config.subdir))
            self._write_strip("%configure_buildtcl {0} {1}".format(self.config.extra_configure, self.config.extra_configure64))
            self.write_make_line()
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")

        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/" + self.config.subdir)
            self.write_build_prepend()
            self.write_variables()
            self.write_profile_payload("configure", "special")
            self._write_strip("%configure_buildtcl {0}".format(self.config.extra_configure_special))
            self.write_make_line(build32=False, build_type="special", pgo=False, pattern=None)
            self._write_strip("popd")

        if self.config.config_opts["build_special2"]:
            self._write_strip("pushd ../build-special2/" + self.config.subdir)
            self.write_build_prepend()
            self.write_variables()
            self.write_profile_payload("configure", "special2")
            self._write_strip("%configure_buildtcl {0}".format(self.config.extra_configure_special2))
            self.write_make_line(build32=False, build_type="special2", pgo=False, pattern=None)
            self._write_strip("popd")

        if self.config.config_opts["32bit"]:
            if self.config.configure_macro_32:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self.write_build_prepend32()
                self.write_32bit_exports()
                self.write_build_append()
                self._write("{} ".format(self.config.configure_macro_32))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("popd")
            else:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self.write_build_prepend()
                self.write_32bit_exports()
                self.write_build_append()
                self._write_strip("%configure_buildtcl {0} {1}".format(self.config.extra_configure, self.config.extra_configure32))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("popd")
        self._write_strip("\n")
        self.write_check()
        self.write_make_install_buildtcl_configure()

    def write_configure_pattern(self):
        """Write configure build pattern to spec file."""
        if self.config.autoreconf:
            # Patches affecting configure.* or Makefile.*, reconf instead
            self.write_configure_ac_pattern()
            return
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_build_prepend()
        self.write_variables()
        self.write_profile_payload("configure")
        if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
            if self.config.configure_macro_pgo:
                if self.config.subdir:
                    self._write_strip("pushd {}".format(self.config.subdir))
                self._write("{}".format(self.get_profile_use_flags()))
                for line in self.config.configure_macro_pgo:
                    self._write("{}\n".format(line))
                self.write_make_line(build32=False, build_type=None, pgo=True, pattern=None)
                if self.config.subdir:
                    self._write_strip("popd")
                self._write_strip("\n")
            elif self.config.configure_macro:
                if self.config.subdir:
                    self._write_strip("pushd {}".format(self.config.subdir))
                self._write("{}".format(self.get_profile_use_flags()))
                for line in self.config.configure_macro:
                    self._write("{}\n".format(line))
                self.write_make_line(build32=False, build_type=None, pgo=True, pattern=None)
                if self.config.subdir:
                    self._write_strip("popd")
                self._write_strip("\n")
            else:
                if self.config.subdir:
                    self._write_strip("pushd {}".format(self.config.subdir))
                self._write_strip("{0}%configure {1} {2}".format(self.get_profile_use_flags(), self.config.extra_configure, self.config.extra_configure64))
                self.write_make_line(build32=False, build_type=None, pgo=True, pattern=None)
                if self.config.subdir:
                    self._write_strip("popd")
                self._write_strip("\n")
        else:
            if self.config.configure_macro:
                if self.config.subdir:
                    self._write_strip("pushd {}".format(self.config.subdir))
                self._write("{}".format(self.get_profile_use_flags()))
                self.write_build_append()
                for line in self.config.configure_macro:
                    self._write("{}\n".format(line))
                self.write_make_line()
                if self.config.subdir:
                    self._write_strip("popd")
                self._write_strip("\n")
            else:
                if self.config.subdir:
                    self._write_strip("pushd {}".format(self.config.subdir))
                self.write_build_append()
                self._write_strip("{0}%configure {1} {2}".format(self.get_profile_use_flags(), self.config.extra_configure, self.config.extra_configure64))
                self.write_make_line()
                if self.config.subdir:
                    self._write_strip("popd")
                self._write_strip("\n")

        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/")
            self.write_build_prepend()
            self.write_variables()
            self.write_profile_payload("configure", "special")
            #self._write_strip("{0}%configure {1}".format(self.get_profile_use_flags(), self.config.extra_configure_special))
            #self.write_make_line(False, "special")
            #self._write_strip("popd")
            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                if self.config.configure_macro_special_pgo:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write("{}".format(self.get_profile_use_flags()))
                    self.write_build_append()
                    for line in self.config.configure_macro_special_pgo:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=False, build_type="special", pgo=True, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
                elif self.config.configure_macro_special:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write("{}".format(self.get_profile_use_flags()))
                    self.write_build_append()
                    for line in self.config.configure_macro_special:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=False, build_type="special", pgo=True, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
                else:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self.write_build_append()
                    self._write_strip("{0}%configure {1}".format(self.get_profile_use_flags(), self.config.extra_configure_special))
                    self.write_make_line(build32=False, build_type="special", pgo=True, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
            else:
                if self.config.configure_macro_special:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self.write_build_append()
                    self._write("{}".format(self.get_profile_use_flags()))
                    for line in self.config.configure_macro_special:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=False, build_type="special", pgo=False, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
                else:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self.write_build_append()
                    self._write_strip("%configure {0}".format(self.config.extra_configure_special))
                    self.write_make_line(build32=False, build_type="special", pgo=False, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")

        if self.config.config_opts["build_special2"]:
            self._write_strip("pushd ../build-special2/" + self.config.subdir)
            self.write_build_prepend()
            self.write_variables()
            self.write_profile_payload("configure", "special2")

            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                if self.config.configure_macro_special2_pgo:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write("{}".format(self.get_profile_use_flags()))
                    for line in self.config.configure_macro_special2_pgo:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=False, build_type="special2", pgo=True, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
                elif self.config.configure_macro_special2:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write("{}".format(self.get_profile_use_flags()))
                    for line in self.config.configure_macro_special2:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=False, build_type="special2", pgo=True, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
                else:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write_strip("{0}%configure {1}".format(self.get_profile_use_flags(), self.config.extra_configure_special2))
                    self.write_make_line(build32=False, build_type="special2", pgo=True, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
            else:
                if self.config.configure_macro_special2:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write("{}".format(self.get_profile_use_flags()))
                    for line in self.config.configure_macro_special2:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=False, build_type="special2", pgo=False, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")
                else:
                    if self.config.subdir:
                        self._write_strip("pushd {}".format(self.config.subdir))
                    self._write_strip("%configure {0}".format(self.config.extra_configure_special2))
                    self.write_make_line(build32=False, build_type="special2", pgo=False, pattern=None)
                    if self.config.subdir:
                        self._write_strip("popd")
                    self._write_strip("popd\n")

        if self.config.config_opts["32bit"]:
            if self.config.configure_macro_32:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self.write_build_prepend32()
                self.write_32bit_exports()
                self.write_build_append()
                for line in self.config.configure_macro_32:
                    self._write("{}\n".format(line))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("popd")
            else:
                self._write_strip("pushd ../build32/" + self.config.subdir)
                self.write_build_prepend32()
                self.write_32bit_exports()
                self.write_build_append()
                self._write_strip("%configure {0} {1} --libdir=/usr/lib32 --build=i686-generic-linux-gnu --host=i686-generic-linux-gnu --target=i686-clr-linux-gnu".format(self.config.extra_configure, self.config.extra_configure32))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("popd")
            if self.config.config_opts["build_special_32"]:
                self._write_strip("pushd ../build-special-32/" + self.config.subdir)
                self.write_build_prepend32()
                self.write_32bit_exports()
                if self.config.configure_macro_special_32:
                    self.write_build_append()
                    for line in self.config.configure_macro_special_32:
                        self._write("{}\n".format(line))
                    self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                    self._write_strip("popd\n")
                else:
                    self.write_build_append()
                    if self.config.extra_configure_special_32:
                        self._write_strip("%configure {0} {1} --libdir=/usr/lib32 --build=i686-generic-linux-gnu --host=i686-generic-linux-gnu --target=i686-clr-linux-gnu".format(self.config.extra_configure, self.config.extra_configure_special_32))
                    else:
                        self._write_strip("%configure {0} {1} --libdir=/usr/lib32 --build=i686-generic-linux-gnu --host=i686-generic-linux-gnu --target=i686-clr-linux-gnu".format(self.config.extra_configure, self.config.extra_configure32))
                    self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                    self._write_strip("popd\n")

        if self.config.config_opts["use_avx2"]:
            self._write_strip("unset PKG_CONFIG_PATH")
            self._write_strip("pushd ../buildavx2/" + self.config.subdir)
            self.write_build_prepend()
            self._write_strip('export CFLAGS="$CFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export FFLAGS="$FFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=native -mtune=native"')
            self._write_strip("%configure {0} {1} ".format(self.config.extra_configure, self.config.extra_configure_avx2))
            self.write_make_line()
            self._write_strip("popd")

        if self.config.config_opts["use_avx512"]:
            self._write_strip("unset PKG_CONFIG_PATH")
            self._write_strip("pushd ../buildavx512/" + self.config.subdir)
            self.write_build_prepend()
            self._write_strip("export CFLAGS=\"$CFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=256\"")
            self._write_strip("export CXXFLAGS=\"$CXXFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=256\"")
            self._write_strip("export FFLAGS=\"$FFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=256\"")
            self._write_strip("export FCFLAGS=\"$FCFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=256\"")
            self._write_strip("export LDFLAGS=\"$LDFLAGS -m64 -march=skylake-avx512\"")
            self._write_strip("%configure {0} {1} ".format(self.config.extra_configure, self.config.extra_configure_avx512))
            self.write_make_line()
            self._write_strip("popd")

        if self.config.config_opts["openmpi"]:
            if self.config.configure_macro_openmpi:
                self._write_strip("pushd ../build-openmpi/" + self.config.subdir)
                self._write_strip(". /usr/share/defaults/etc/profile.d/modules.sh")
                self._write_strip("module load openmpi")
                self.write_build_prepend()
                for line in self.config.configure_macro_openmpi:
                    self._write("{}\n".format(line))
                self.write_make_line()
                self._write_strip("module unload openmpi")
                self._write_strip("popd")
            else:
                self._write_strip("pushd ../build-openmpi/" + self.config.subdir)
                self._write_strip(". /usr/share/defaults/etc/profile.d/modules.sh")
                self._write_strip("module load openmpi")
                self.write_build_prepend()
                self._write_strip('export CFLAGS="$CFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export FFLAGS="$FFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=native -mtune=native"')
                self._write_strip("./configure {0} \\\n{1} ".format(self.config.conf_args_openmpi, self.config.extra_configure_openmpi))
                self.write_make_line()
                self._write_strip("module unload openmpi")
                self._write_strip("popd")
        self._write_strip("\n")
        self.write_check()
        self.write_make_install()

    def write_configure_ac_pattern(self):
        """Write build pattern for configure.ac style build."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_variables()
        self._write_strip(r"sd -r '\s--dirty\s' ' ' .")
        self._write_strip(r"sd -r 'git describe' 'git describe --abbrev=0' .")
        if self.config.config_opts["disable_maintainer"]:
            self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
        self.write_profile_payload("configure_ac")
        if self.config.configure_macro:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write("{} {} ".format(self.get_profile_use_flags(), self.config.configure_macro))
            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                self.write_make_line(build32=False, build_type=None, pgo=True, pattern=None)
            else:
                self.write_make_line(build32=False, build_type=None, pgo=False, pattern=None)
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")
        else:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip("{0}%reconfigure {1} {2} ".format(self.get_profile_use_flags(), self.config.extra_configure_pgo, self.config.extra_configure64_pgo))
            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                self.write_make_line(build32=False, build_type=None, pgo=True, pattern=None)
            else:
                self.write_make_line(build32=False, build_type=None, pgo=False, pattern=None)
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")

        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/")
            self.write_build_prepend()
            self.write_variables()
            self._write_strip(r"sd -r '\s--dirty\s' ' ' .")
            self._write_strip(r"sd -r 'git describe' 'git describe --abbrev=0' .")
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self.write_profile_payload("configure_ac", "special")
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip("{0}%reconfigure {1} ".format(self.get_profile_use_flags(), self.config.extra_configure_special))
            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                self.write_make_line(build32=False, build_type="special", pgo=True, pattern=None)
            else:
                self.write_make_line(build32=False, build_type="special", pgo=False, pattern=None)
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("popd")

        if self.config.config_opts["build_special2"]:
            self._write_strip("pushd ../build-special2/")
            self.write_build_prepend()
            self.write_variables()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self.write_profile_payload("configure_ac", "special2")
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip("{0}%reconfigure {1} ".format(self.get_profile_use_flags(), self.config.extra_configure_special2))
            self.write_make_line(build32=False, build_type="special2", pgo=False, pattern=None)
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("popd")

        if self.config.config_opts["32bit"]:
            self._write_strip("pushd ../build32/" + self.config.subdir)
            self.write_build_prepend32()
            self.write_32bit_exports()
            self.write_build_append()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self._write_strip("%reconfigure {0} {1} --libdir=/usr/lib32 --build=i686-generic-linux-gnu --host=i686-generic-linux-gnu --target=i686-clr-linux-gnu".format(self.config.extra_configure, self.config.extra_configure32))
            self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
            self._write_strip("popd")

        if self.config.config_opts["use_avx2"]:
            self._write_strip("unset PKG_CONFIG_PATH")
            self._write_strip("pushd ../buildavx2/" + self.config.subdir)
            self.write_build_prepend()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self._write_strip('export CFLAGS="$CFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export FFLAGS="$FFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=native -mtune=native"')
            self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=native -mtune=native"')
            self._write_strip("%reconfigure {0} {1} ".format(self.config.extra_configure, self.config.extra_configure_avx2))
            self.write_make_line()
            self._write_strip("popd")

        if self.config.config_opts["use_avx512"]:
            self._write_strip("unset PKG_CONFIG_PATH")
            self._write_strip("pushd ../buildavx512/" + self.config.subdir)
            self.write_build_prepend()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self._write_strip('export CFLAGS="$CFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
            self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
            self._write_strip('export FFLAGS="$FFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
            self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
            self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=skylake-avx512"')
            self._write_strip("%reconfigure {0} {1} ".format(self.config.extra_configure, self.config.extra_configure_avx512))
            self.write_make_line()
            self._write_strip("popd")

        self._write_strip("\n")
        self.write_check()
        self.write_make_install()

    def write_make_pattern(self):
        """Write build pattern for make."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        if not self.config.config_opts["32bit_only"]:
            self.write_build_prepend()
            self.write_variables()
            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                self.write_profile_payload(pattern="make", build_type=None)
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                self.write_make_line(build32=False, build_type=None, pgo=True, pattern="make")
            else:
                self.write_make_line(build32=False, build_type=None, pgo=None, pattern="make")
            if self.config.subdir:
                self._write_strip("popd")
            self._write_strip("\n")
            if self.config.config_opts["build_special"]:
                self._write_strip("pushd ../build-special/" + self.config.subdir)
                self.write_build_prepend()
                self.write_variables()
                self.write_profile_payload(pattern="make", build_type=None)
                self.write_make_line(build32=False, build_type=None, pgo=False, pattern="make")
                self._write_strip("popd")
            if self.config.config_opts["build_special2"]:
                self._write_strip("pushd ../build-special2/" + self.config.subdir)
                self.write_build_prepend()
                self.write_variables()
                self.write_profile_payload(pattern="make", build_type=None)
                self.write_make_line(build32=False, build_type=None, pgo=False, pattern="make")
                self._write_strip("popd")
            if self.config.config_opts["use_avx2"]:
                self._write_strip("pushd ../buildavx2" + self.config.subdir)
                self.write_build_prepend()
                self._write_strip('export CFLAGS="$CFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export FFLAGS="$FFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=native -mtune=native"')
                self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=native -mtune=native"')
                self.write_make_line()
                self._write_strip("popd")
            if self.config.config_opts["use_avx512"]:
                self._write_strip("pushd ../buildavx512" + self.config.subdir)
                self.write_build_prepend()
                self._write_strip('export CFLAGS="$CFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
                self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
                self._write_strip('export FFLAGS="$FFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
                self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=skylake-avx512 -mprefer-vector-width=512"')
                self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=skylake-avx512"')
                self.write_make_line()
                self._write_strip("popd")
        if self.config.config_opts["32bit"]:
            self._write_strip("pushd ../build32/" + self.config.subdir)
            self.write_build_prepend32()
            self.write_32bit_exports()
            self.write_build_append()
            self.write_make_line(build32=True, build_type=None, pgo=False, pattern="make")
            self._write_strip("popd")

        self._write_strip("\n")
        self.write_check()
        self.write_make_install()

    def write_autogen_pattern(self):
        """Write build pattern for autogen packages."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_variables()
        self._write_strip(r"sd -r '\s--dirty\s' ' ' .")
        self._write_strip(r"sd -r 'git describe' 'git describe --abbrev=0' .")
        if self.config.config_opts["disable_maintainer"]:
            self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")

        if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
            self.write_profile_payload("autogen")
            if self.config.extra_configure_pgo or self.config.extra_configure64_pgo:
                self._write_strip("{0}%autogen {1} {2} ".format(self.get_profile_use_flags(), self.config.extra_configure_pgo, self.config.extra_configure64_pgo))
            elif self.config.extra_configure or self.config.extra_configure64:
                self._write_strip("{0}%autogen {1} {2} ".format(self.get_profile_use_flags(), self.config.extra_configure, self.config.extra_configure64))
            self.write_make_line(build32=False, build_type=None, pgo=True, pattern=None)
            self._write_strip("\n")
        else:
            self._write_strip("%autogen {0} {1}".format(self.config.extra_configure, self.config.extra_configure64))
            self.write_make_line(build32=False, build_type=None, pgo=False, pattern=None)
            self._write_strip("\n")

        if self.config.config_opts["32bit"]:
            self._write_strip("pushd ../build32/" + self.config.subdir)
            self.write_build_prepend32()
            self.write_32bit_exports()
            self.write_build_append()
            self._write_strip("%autogen {0} {1} --libdir=/usr/lib32 --build=i686-generic-linux-gnu --host=i686-generic-linux-gnu --target=i686-clr-linux-gnu".format(self.config.extra_configure, self.config.extra_configure32))
            self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
            self._write_strip("popd")

        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/" + self.config.subdir)
            self.write_build_prepend()
            self.write_variables()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self.write_profile_payload("autogen", "special")
            self._write_strip("{0}%autogen {1} ".format(self.get_profile_use_flags(), self.config.extra_configure_special))
            self.write_make_line()
            self._write_strip("popd")

        if self.config.config_opts["use_avx2"]:
            self._write_strip("pushd ../buildavx2/" + self.config.subdir)
            self.write_build_prepend()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self._write_strip('export CFLAGS="$CFLAGS -m64 -march=native -mtune=native "')
            self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=native -mtune=native "')
            self._write_strip('export FFLAGS="$FFLAGS -m64 -march=native -mtune=native "')
            self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=native -mtune=native "')
            self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=native -mtune=native "')
            self._write_strip("%autogen {0} {1} ".format(self.config.extra_configure, self.config.extra_configure_avx2))
            self.write_make_line()
            self._write_strip("popd")

        if self.config.config_opts["use_avx512"]:
            self._write_strip("pushd ../buildavx512/" + self.config.subdir)
            self.write_build_prepend()
            if self.config.config_opts["disable_maintainer"]:
                self._write_strip(r"sd --flags mi '^AC_INIT\((.*\n.*\)|.*\))' '$0\nAM_MAINTAINER_MODE([disable])' configure.ac")
            self._write_strip('export CFLAGS="$CFLAGS -m64 -march=skylake-avx512 "')
            self._write_strip('export CXXFLAGS="$CXXFLAGS -m64 -march=skylake-avx512 "')
            self._write_strip('export FFLAGS="$FFLAGS -m64 -march=skylake-avx512 "')
            self._write_strip('export FCFLAGS="$FCFLAGS -m64 -march=skylake-avx512 "')
            self._write_strip('export LDFLAGS="$LDFLAGS -m64 -march=skylake-avx512 "')
            self._write_strip("%autogen {0} {1} ".format(self.config.extra_configure, self.config.extra_configure_avx512))
            self.write_make_line()
            self._write_strip("popd")
        self._write_strip("\n")
        self.write_check()
        self.write_make_install()

    def write_distutils3_pattern(self):
        """Write build pattern for python packages using distutils3."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_variables()
        self._write_strip("export MAKEFLAGS=%{?_smp_mflags}")
        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)
        if self.config.make_prepend:
            self._write_strip("## make_prepend content")
            for line in self.config.make_prepend:
                self._write("{}\n".format(line))
            self._write_strip("## make_prepend end")
        if self.config.make_macro:
            self._write_strip("## make_macro start")
            for line in self.config.make_macro:
                self._write("{}\n".format(line))
            self._write_strip("## make_macro end")
        else:
            self._write_strip("if [ ! -f setup.py ]; then")
            self._write('printf \"#!/usr/bin/env python\\nfrom setuptools import setup\\nsetup()\" > setup.py\n')
            self._write_strip('chmod +x setup.py')
            self._write_strip("python3 setup.py build -j 16 " + self.config.extra_configure)
            self._write_strip("else")
            self._write_strip("python3 setup.py build -j 16 " + self.config.extra_configure)
            self._write_strip("fi")
        if self.config.subdir:
            self._write_strip("popd")
        if self.tests_config and not self.config.config_opts["skip_tests"]:
            self._write_strip("\n%check")
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            # Prevent setuptools from hitting the internet
            self.write_proxy_exports()
            self._write_strip(self.tests_config)
            if self.config.subdir:
                self._write_strip("popd")
        self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)
        self._write_strip("export MAKEFLAGS=%{?_smp_mflags}")
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self.write_license_files()
        self._write_strip("python3 -tt setup.py build -j 16 install --root=%{buildroot}")
        if self.config.subdir:
            self._write_strip("popd")
        self._write_strip("echo ----[ mark ]----")
        self._write_strip("cat %{buildroot}/usr/lib/python3*/site-packages/*/requires.txt || :")
        self._write_strip("echo ----[ mark ]----")
        self.write_find_lang()

    def write_distutils36_pattern(self):
        """Write build pattern for python packages using distutils36."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_variables()
        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)
        self._write_strip("python3.6 setup.py build -b py3 " + self.config.extra_configure)
        self._write_strip("\n")
        if self.tests_config and not self.config.config_opts["skip_tests"]:
            self._write_strip("%check")
            # Prevent setuptools from hitting the internet
            self.write_proxy_exports()
            self._write_strip(self.tests_config)
        if self.config.subdir:
            self._write_strip("popd")
        self.write_build_append()
        self._write_strip("%install")
        self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()

        self.write_license_files()

        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)
        self._write_strip("python3.6 -tt setup.py build -b py3 install --root=%{buildroot} --force")
        if self.config.subdir:
            self._write_strip("popd")
        self._write_strip("echo ----[ mark ]----")
        self._write_strip("cat %{buildroot}/usr/lib/python3*/site-packages/*/requires.txt || :")
        self._write_strip("echo ----[ mark ]----")
        self.write_find_lang()

    def write_R_pattern(self):
        """Write build pattern for R packages."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self._write_strip("\n")

        self._write_strip("%install")
        self._write_strip("export SOURCE_DATE_EPOCH={}".format(int(time.time())))
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self._write_strip("export LANG=C.UTF-8")
        self._write_strip('export CFLAGS="$CFLAGS -O3 -flto -fno-semantic-interposition "\n')
        self._write_strip('export FCFLAGS="$FFLAGS -O3 -flto -fno-semantic-interposition "\n')
        self._write_strip('export FFLAGS="$FFLAGS -O3 -flto -fno-semantic-interposition "\n')
        self._write_strip('export CXXFLAGS="$CXXFLAGS -O3 -flto -fno-semantic-interposition "\n')
        self._write_strip("export AR=gcc-ar\n")
        self._write_strip("export RANLIB=gcc-ranlib\n")
        self._write_strip('export LDFLAGS="$LDFLAGS  -Wl,-z -Wl,relro"\n')

        self._write_strip("mkdir -p %{buildroot}/usr/lib64/R/library")
        self._write_strip("\n")
        self._write_strip("mkdir -p ~/.R")
        self._write_strip("mkdir -p ~/.stash")

        self._write_strip('echo "CFLAGS = $CFLAGS -march=native -mtune=native -ftree-vectorize " > ~/.R/Makevars')
        self._write_strip('echo "FFLAGS = $FFLAGS -march=native -mtune=native -ftree-vectorize " >> ~/.R/Makevars')
        self._write_strip('echo "CXXFLAGS = $CXXFLAGS -march=native -mtune=native -ftree-vectorize " >> ~/.R/Makevars')

        self._write_strip("R CMD INSTALL " "--install-tests " "--built-timestamp=${SOURCE_DATE_EPOCH} " "--build  -l " "%{buildroot}/usr/lib64/R/library " + self.content.rawname)
        self._write_strip('for i in `find %{buildroot}/usr/lib64/R/ -name "*.so"`; do mv $i $i.avx2 ; mv $i.avx2 ~/.stash/; done\n')

        self._write_strip('echo "CFLAGS = $CFLAGS -march=skylake-avx512 -ftree-vectorize " > ~/.R/Makevars')
        self._write_strip('echo "FFLAGS = $FFLAGS -march=skylake-avx512 -ftree-vectorize " >> ~/.R/Makevars')
        self._write_strip('echo "CXXFLAGS = $CXXFLAGS -march=skylake-avx512 -ftree-vectorize " >> ~/.R/Makevars')

        self._write_strip(
            "R CMD INSTALL " "--preclean " "--install-tests " "--no-test-load " "--built-timestamp=${SOURCE_DATE_EPOCH} " "--build  -l " "%{buildroot}/usr/lib64/R/library " + self.content.rawname
        )
        self._write_strip('for i in `find %{buildroot}/usr/lib64/R/ -name "*.so"`; do mv $i $i.avx512 ; mv $i.avx512 ~/.stash/; done\n')

        self._write_strip('echo "CFLAGS = $CFLAGS -ftree-vectorize " > ~/.R/Makevars')
        self._write_strip('echo "FFLAGS = $FFLAGS -ftree-vectorize " >> ~/.R/Makevars')
        self._write_strip('echo "CXXFLAGS = $CXXFLAGS -ftree-vectorize " >> ~/.R/Makevars')

        self._write_strip("R CMD INSTALL " "--preclean " "--install-tests " "--built-timestamp=${SOURCE_DATE_EPOCH} " "--build  -l " "%{buildroot}/usr/lib64/R/library " + self.content.rawname)
        self._write_strip("cp ~/.stash/* %{buildroot}/usr/lib64/R/library/*/libs/ || :")

        self._write_strip("%{__rm} -rf %{buildroot}%{_datadir}/R/library/R.css")
        self.write_find_lang()
        self.write_check()

    def write_ruby_pattern(self):
        """Write build pattern for ruby packages."""
        self.write_prep(ruby_pattern=True)
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("export LANG=C.UTF-8")
        self._write_strip("gem build {}.gemspec".format(self.name))
        self.write_build_append()
        self._write_strip("\n")

        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("%global gem_dir $(ruby -e'puts Gem.default_dir')")
        self._write_strip("gem install -V \\")
        self._write_strip("  --local \\")
        self._write_strip("  --force \\")
        self._write_strip("  --install-dir .%{gem_dir} \\")
        self._write_strip("  --bindir .%{_bindir} \\")
        self._write_strip(" {}.gem".format(self.content.gem_subdir))
        self._write_strip("\n")

        self._write_strip("mkdir -p %{buildroot}%{gem_dir}")
        self._write_strip("cp -pa .%{gem_dir}/* \\")
        self._write_strip("        %{buildroot}%{gem_dir}")
        self._write_strip("\n")

        self._write_strip("if [ -d .%{_bindir} ]; then")
        self._write_strip("    mkdir -p %{buildroot}%{_bindir}")
        self._write_strip("    cp -pa .%{_bindir}/* \\")
        self._write_strip("        %{buildroot}%{_bindir}/")
        self._write_strip("fi")
        self._write_strip("\n")
        self.write_find_lang()
        self.write_check()

    def write_cmake_pattern(self):
        """Write cmake pattern to spec file."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)

        if self.config.subdir:
            self._write_strip("pushd " + self.config.subdir)

        if not self.config.config_opts["32bit_only"]:
            self._write_strip("mkdir -p clr-build")
            self._write_strip("pushd clr-build")
            if self.config.profile_payload and self.config.profile_payload[0] and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                self.write_variables()
                init = f"{self.get_profile_generate_flags()}"
                post = f"{self.get_profile_use_flags()}"
                self._write_strip("if [ ! -f statuspgo ]; then")
                self._write_strip("echo PGO Phase 1")
                if init:
                    self._write_strip(init)
                if self.config.cmake_macro:
                    for line in self.config.cmake_macro:
                        self._write("{}\n".format(line))
                else:
                    self._write_strip("%cmake {} {} {}".format(self.config.cmake_srcdir, self.extra_cmake, self.extra_cmake_64))
                self.write_make_line()
                self._write_strip("\n")
                self.write_profile_payload_content(pattern="cmake", build_type=None)
                if self.config.custom_clean_pgo:
                    self._write_strip("{}\n".format(self.config.custom_clean_pgo))
                else:
                    self._write_strip("\nfind . -type f,l -not -name '*.gcno' -not -name 'statuspgo*' -delete -print")
                self._write_strip("echo USED > statuspgo")
                self._write_strip("fi")
                self._write_strip("if [ -f statuspgo ]; then")
                self._write_strip("echo PGO Phase 2\n")
                if post:
                    self._write_strip(post)
                if self.config.cmake_macro_pgo:
                    for line in self.config.cmake_macro_pgo:
                        self._write("{}\n".format(line))
                elif self.config.cmake_macro:
                    for line in self.config.cmake_macro:
                        self._write("{}\n".format(line))
                elif self.config.extra_cmake_pgo:
                    self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake_pgo))
                else:
                    self._write_strip("%cmake {} {} {}".format(self.config.cmake_srcdir, self.extra_cmake, self.extra_cmake_64))
                self.write_make_line()
                self._write_strip("fi")
                self._write_strip("popd")
            else:
                self.write_variables()
                if self.config.cmake_macro:
                    for line in self.config.cmake_macro:
                        self._write("{}\n".format(line))
                else:
                    self._write_strip("%cmake {} {} {}".format(self.config.cmake_srcdir, self.extra_cmake, self.extra_cmake_64))
                #self.write_profile_payload("cmake")
                self.write_make_line()
                self._write_strip("popd")

            if self.config.config_opts["build_special"]:
                if self.config.profile_payload and self.config.profile_payload[0] and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
                    self._write_strip("mkdir -p clr-build-special")
                    self._write_strip("pushd clr-build-special")
                    self.write_build_prepend()
                    self.write_variables()
                    init = f"{self.get_profile_generate_flags()}"
                    post = f"{self.get_profile_use_flags()}"
                    self._write_strip("if [ ! -f statuspgo.special ]; then")
                    self._write_strip("echo PGO Phase 1")
                    if init:
                        self._write_strip(init)
                    if self.config.cmake_macro_special:
                        for line in self.config.cmake_macro_special:
                            self._write("{}\n".format(line))
                    else:
                        self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake_special))
                    self.write_make_line()
                    self._write_strip("\n")
                    self.write_profile_payload_content(pattern="cmake", build_type="special")
                    if self.config.custom_clean_pgo:
                        self._write_strip("{}\n".format(self.config.custom_clean_pgo))
                    else:
                        self._write_strip("\nfind . -type f,l -not -name '*.gcno' -not -name 'statuspgo*' -delete -print\n")
                    self._write_strip("echo USED > statuspgo.special\n")
                    self._write_strip("fi")
                    self._write_strip("if [ -f statuspgo.special ]; then")
                    self._write_strip("echo PGO Phase 2\n")
                    if post:
                        self._write_strip(post)
                    if self.config.cmake_macro_special:
                        for line in self.config.cmake_macro_special:
                            self._write("{}\n".format(line))
                    elif self.config.extra_cmake_special_pgo:
                        self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake_special_pgo))
                    else:
                        self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake_special))
                    self.write_make_line()
                    self._write_strip("fi")
                    self._write_strip("popd")
                else:
                    self._write_strip("mkdir -p clr-build-special")
                    self._write_strip("pushd clr-build-special")
                    self.write_build_prepend()
                    self.write_variables()
                    if self.config.cmake_macro_special:
                        for line in self.config.cmake_macro_special:
                            self._write("{}\n".format(line))
                    else:
                        self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake_special))
                    #self.write_profile_payload("cmake")
                    self.write_make_line()
                    self._write_strip("popd")

            if self.config.config_opts["use_avx2"]:
                self._write_strip("mkdir -p clr-build-avx2")
                self._write_strip("pushd clr-build-avx2")
                saved_avx2flags = self.need_avx2_flags
                self.need_avx2_flags = True
                self.write_build_prepend()
                self.write_variables()
                self.need_avx2_flags = saved_avx2flags
                self._write_strip('export CFLAGS="$CFLAGS -march=native -mtune=native -m64"')
                self._write_strip('export CXXFLAGS="$CXXFLAGS -march=native -mtune=native -m64"')
                self._write_strip('export FFLAGS="$FFLAGS -march=native -mtune=native -m64"')
                self._write_strip('export FCFLAGS="$FCFLAGS -march=native -mtune=native -m64"')
                self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake))
                self.write_make_line()
                self._write_strip("popd")

            if self.config.config_opts["use_avx512"]:
                self._write_strip("mkdir -p clr-build-avx512")
                self._write_strip("pushd clr-build-avx512")
                saved_avx512flags = self.need_avx512_flags
                self.need_avx512_flags = True
                self.write_build_prepend()
                self.write_variables()
                self.need_avx512_flags = saved_avx512flags
                self._write_strip('export CFLAGS="$CFLAGS -march=skylake-avx512 -m64 "')
                self._write_strip('export CXXFLAGS="$CXXFLAGS -march=skylake-avx512 -m64 "')
                self._write_strip('export FFLAGS="$FFLAGS -march=skylake-avx512 -m64 "')
                self._write_strip('export FCFLAGS="$FCFLAGS -march=skylake-avx512 -m64 "')
                self._write_strip("%cmake {} {}".format(self.config.cmake_srcdir, self.extra_cmake))
                self.write_make_line()
                self._write_strip("popd")

            if self.config.config_opts["openmpi"]:
                self._write_strip("mkdir -p clr-build-openmpi")
                self._write_strip("pushd clr-build-openmpi")
                self._write_strip(". /usr/share/defaults/etc/profile.d/modules.sh")
                self._write_strip("module load openmpi")
                saved_avx2flags = self.need_avx2_flags
                self.need_avx2_flags = True
                self.write_build_prepend()
                self.write_variables()
                self.need_avx2_flags = saved_avx2flags
                self._write_strip('export CFLAGS="$CFLAGS -march=native -mtune=native -m64"')
                self._write_strip('export CXXFLAGS="$CXXFLAGS -march=native -mtune=native -m64"')
                self._write_strip('export FCFLAGS="$FCFLAGS -march=native -mtune=native -m64"')
                self._write_strip('export FFLAGS="$FFLAGS -march=native -mtune=native -m64"')
                self.write_cmake_line_openmpi()
                self.write_make_line()
                self._write_strip("module unload openmpi")
                self._write_strip("popd")

        if self.config.config_opts["32bit"]:
            if self.config.cmake_macro_32:
                self._write_strip("mkdir -p clr-build32")
                self._write_strip("pushd clr-build32")
                self.write_build_prepend32()
                self.write_32bit_exports()
                self.write_build_append()
                for line in self.config.cmake_macro_32:
                    self._write("{}\n".format(line))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("unset PKG_CONFIG_PATH")
                self._write_strip("popd")
            else:
                self._write_strip("mkdir -p clr-build32")
                self._write_strip("pushd clr-build32")
                self.write_build_prepend32()
                self.write_32bit_exports()
                self.write_build_append()
                self._write_strip("%cmake -DLIB_INSTALL_DIR:PATH=/usr/lib32 " "-DCMAKE_INSTALL_LIBDIR=/usr/lib32 " "-DLIB_SUFFIX=32 " "{} {} {}".format(self.config.cmake_srcdir, self.extra_cmake, self.extra_cmake_32))
                self.write_make_line(build32=True, build_type=None, pgo=False, pattern=None)
                self._write_strip("unset PKG_CONFIG_PATH")
                self._write_strip("popd")

        if self.config.subdir:
            self._write_strip("popd")

        self._write_strip("\n")
        self.write_check()

        self.write_cmake_install()

    def write_qmake_pattern(self):
        """Write qmake build pattern to spec file."""
        extra_qmake_args = ""
        if self.config.config_opts["use_clang"]:
            extra_qmake_args = "-spec linux-clang "
        if self.config.config_opts["use_lto"]:
            extra_qmake_args += "-config ltcg "

        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("export LANG=C.UTF-8")
        self.write_variables()

        if self.config.configure_macro:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self.write_build_append()
            for line in self.config.configure_macro:
                self._write("{}\n".format(line))
            self._write_strip("test -r config.log && cat config.log")
            self.write_make_line()
            if self.config.subdir:
                self._write_strip("popd")
        else:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self.write_build_append()
            self._write_strip("%qmake {} {}".format(extra_qmake_args, self.config.extra_configure))
            self._write_strip("test -r config.log && cat config.log")
            self.write_make_line()
            if self.config.subdir:
                self._write_strip("popd")

        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/" + self.config.subdir)
            self.write_variables()
            self.write_build_append()
            self._write("%qmake 'QT_CPU_FEATURES.x86_64 += avx avx2 bmi bmi2 f16c fma lzcnt popcnt'\\\n")
            self._write("QMAKE_CFLAGS+=-march=native QMAKE_CFLAGS+=-mtune=native QMAKE_CXXFLAGS+=-march=native QMAKE_CXXFLAGS+=-mtune=native \\\n")
            self._write("QMAKE_LFLAGS+=-march=native QMAKE_LFLAGS+=-mtune=native {} {}\n".format(extra_qmake_args, self.config.extra_configure_special))
            self.write_make_line()
            self._write_strip("popd")

        if self.config.config_opts["use_avx2"]:
            self._write_strip("pushd ../buildavx2/" + self.config.subdir)
            self.write_build_append()
            self._write("%qmake 'QT_CPU_FEATURES.x86_64 += avx avx2 bmi bmi2 f16c fma lzcnt popcnt'\\\n")
            self._write("QMAKE_CFLAGS+=-march=native QMAKE_CFLAGS+=-mtune=native QMAKE_CXXFLAGS+=-march=native QMAKE_CXXFLAGS+=-mtune=native \\\n")
            self._write("QMAKE_LFLAGS+=-march=native QMAKE_LFLAGS+=-mtune=native {} {}\n".format(extra_qmake_args, self.config.extra_configure))
            self.write_make_line()
            self._write_strip("popd")
        self._write_strip("\n")
        self.write_make_install()

    def write_cargo_pattern(self):
        """Write cargo build pattern to spec file."""
        if self.config.config_opts["altcargo1"]:
            self.write_prep()
            self._write_strip("%build")
            self.write_build_prepend()
            self.write_proxy_exports()
            self._write_strip("mkdir -p $HOME/.cargo")
            if self.config.config_opts["altcargo1_lto"]:
                self._write('printf \"[build]\\nrustflags = [\\"-Ctarget-cpu=native\\", \\"-Ztune-cpu=native\\", \\"-Cprefer-dynamic=no\\", \\"-Copt-level=3\\", \\"-Clto=fat\\", \\"-Clinker-plugin-lto\\", \\"-Cembed-bitcode=yes\\", \\"-Clinker=clang\\", \\"-Clink-arg=-flto\\", \\"-Clink-arg=-fuse-ld=lld\\", \\"-Clink-arg=-Wl,--lto-O3\\", \\"-Clink-arg=-Wl,-O2\\", \\"-Clink-arg=-Wl,--hash-style=gnu\\", \\"-Clink-arg=-Wl,--enable-new-dtags\\", \\"-Clink-arg=-Wl,--build-id=sha1\\", \\"-Clink-arg=-fno-stack-protector\\", \\"-Clink-arg=-Wl,--as-needed\\", \\"-Clink-arg=-O3\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-mtune=native\\", \\"-Clink-arg=-falign-functions=32\\", \\"-Clink-arg=-fasynchronous-unwind-tables\\", \\"-Clink-arg=-funroll-loops\\", \\"-Clink-arg=-fvisibility-inlines-hidden\\", \\"-Clink-arg=-static-libstdc++\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-static-libgcc\\", \\"-Clink-arg=-pthread\\", \\"-Clink-arg=-lpthread\\", \\"-Clink-arg=-L.\\"]\\n[net]\\ngit-fetch-with-cli = true\\n[profile.release]\\nopt-level = 3\\nlto = \\"fat\\"\\n\" > $HOME/.cargo/config.toml\n')
            else:
                self._write('printf \"[build]\\nrustflags = [\\"-Ctarget-cpu=native\\", \\"-Ztune-cpu=native\\", \\"-Cprefer-dynamic=no\\", \\"-Copt-level=3\\", \\"-Clinker-plugin-lto\\", \\"-Cembed-bitcode=yes\\", \\"-Clinker=clang\\", \\"-Clink-arg=-flto\\", \\"-Clink-arg=-fuse-ld=lld\\", \\"-Clink-arg=-Wl,--lto-O3\\", \\"-Clink-arg=-Wl,-O2\\", \\"-Clink-arg=-Wl,--hash-style=gnu\\", \\"-Clink-arg=-Wl,--enable-new-dtags\\", \\"-Clink-arg=-Wl,--build-id=sha1\\", \\"-Clink-arg=-fno-stack-protector\\", \\"-Clink-arg=-Wl,--as-needed\\", \\"-Clink-arg=-O3\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-mtune=native\\", \\"-Clink-arg=-falign-functions=32\\", \\"-Clink-arg=-fasynchronous-unwind-tables\\", \\"-Clink-arg=-funroll-loops\\", \\"-Clink-arg=-fvisibility-inlines-hidden\\", \\"-Clink-arg=-static-libstdc++\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-static-libgcc\\", \\"-Clink-arg=-pthread\\", \\"-Clink-arg=-lpthread\\", \\"-Clink-arg=-L.\\"]\\n[net]\\ngit-fetch-with-cli = true\\n[profile.release]\\nopt-level = 3\\nlto = \\"fat\\"\\n\" > $HOME/.cargo/config.toml\n')
            self._write_strip("unset CFLAGS")
            self._write_strip("unset CXXFLAGS")
            self._write_strip("unset FCFLAGS")
            self._write_strip("unset FFLAGS")
            self._write_strip("unset CFFLAGS")
            self._write_strip("unset LDFLAGS")
            self._write_strip("export CARGO_NET_GIT_FETCH_WITH_CLI=true")
            self._write_strip("export CARGO_PROFILE_RELEASE_LTO=fat")
            self._write_strip("export CARGO_PROFILE_RELEASE_OPT_LEVEL=3")
            self._write_strip("export CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=clang")
            self._write_strip("export SSL_CERT_FILE=/var/cache/ca-certs/anchors/ca-certificates.crt")
            self._write_strip("export CARGO_HTTP_CAINFO=/var/cache/ca-certs/anchors/ca-certificates.crt")
            self._write_strip("export CARGO_TARGET_DIR=target")
            # self._write_strip('export RUSTFLAGS="-Ctarget-cpu=native -Ztune-cpu=native -Cprefer-dynamic=no -Copt-level=3 -Clto=fat -Clinker-plugin-lto -Cembed-bitcode=yes -Clinker=clang -Clink-arg=-flto -Clink-arg=-fuse-ld=lld -Clink-arg=-Wl,--lto-O3 -Clink-arg=-Wl,-O2 -Clink-arg=-Wl,--hash-style=gnu -Clink-arg=-Wl,--enable-new-dtags -Clink-arg=-Wl,--build-id=sha1 -Clink-arg=-fno-stack-protector -Clink-arg=-Wl,--as-needed -Clink-arg=-O3 -Clink-arg=-march=native -Clink-arg=-mtune=native -Clink-arg=-falign-functions=32 -Clink-arg=-fasynchronous-unwind-tables -Clink-arg=-funroll-loops -Clink-arg=-fvisibility-inlines-hidden -Clink-arg=-static-libstdc++ -Clink-arg=-march=native -Clink-arg=-static-libgcc -Clink-arg=-pthread -Clink-arg=-lpthread -Clink-arg=-L."')
            self.apply_patches_cargo()
            if self.config.make_macro:
                self._write_strip("## make_macro start")
                for line in self.config.make_macro:
                    self._write("{}\n".format(line))
                self._write_strip("## make_macro end")
            #else:
                #self._write_strip("cargo upgrade")
                #self._write_strip("cargo update --verbose")
                #self._write_strip("cargo fetch --verbose")
                #self._write_strip("cargo fetch --verbose --target x86_64-unknown-linux-gnu")
                #self._write_strip('cargo build %{{?_smp_mflags}} --all-features --verbose --target-dir x86_64-unknown-linux-gnu --release {0}'.format(self.config.extra_configure))
            self.write_build_append()
            self._write_strip("\n")
            self._write_strip("%install")
            self.write_install_prepend()
            self._write_strip("mkdir -p $HOME/.cargo")
            if self.config.config_opts["altcargo1_lto"]:
                self._write('printf \"[build]\\nrustflags = [\\"-Ctarget-cpu=native\\", \\"-Ztune-cpu=native\\", \\"-Cprefer-dynamic=no\\", \\"-Copt-level=3\\", \\"-Clto=fat\\", \\"-Clinker-plugin-lto\\", \\"-Cembed-bitcode=yes\\", \\"-Clinker=clang\\", \\"-Clink-arg=-flto\\", \\"-Clink-arg=-fuse-ld=lld\\", \\"-Clink-arg=-Wl,--lto-O3\\", \\"-Clink-arg=-Wl,-O2\\", \\"-Clink-arg=-Wl,--hash-style=gnu\\", \\"-Clink-arg=-Wl,--enable-new-dtags\\", \\"-Clink-arg=-Wl,--build-id=sha1\\", \\"-Clink-arg=-fno-stack-protector\\", \\"-Clink-arg=-Wl,--as-needed\\", \\"-Clink-arg=-O3\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-mtune=native\\", \\"-Clink-arg=-falign-functions=32\\", \\"-Clink-arg=-fasynchronous-unwind-tables\\", \\"-Clink-arg=-funroll-loops\\", \\"-Clink-arg=-fvisibility-inlines-hidden\\", \\"-Clink-arg=-static-libstdc++\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-static-libgcc\\", \\"-Clink-arg=-pthread\\", \\"-Clink-arg=-lpthread\\", \\"-Clink-arg=-L.\\"]\\n[net]\\ngit-fetch-with-cli = true\\n[profile.release]\\nopt-level = 3\\nlto = \\"fat\\"\\n\" > $HOME/.cargo/config.toml\n')
            else:
                self._write('printf \"[build]\\nrustflags = [\\"-Ctarget-cpu=native\\", \\"-Ztune-cpu=native\\", \\"-Cprefer-dynamic=no\\", \\"-Copt-level=3\\", \\"-Clinker-plugin-lto\\", \\"-Cembed-bitcode=yes\\", \\"-Clinker=clang\\", \\"-Clink-arg=-flto\\", \\"-Clink-arg=-fuse-ld=lld\\", \\"-Clink-arg=-Wl,--lto-O3\\", \\"-Clink-arg=-Wl,-O2\\", \\"-Clink-arg=-Wl,--hash-style=gnu\\", \\"-Clink-arg=-Wl,--enable-new-dtags\\", \\"-Clink-arg=-Wl,--build-id=sha1\\", \\"-Clink-arg=-fno-stack-protector\\", \\"-Clink-arg=-Wl,--as-needed\\", \\"-Clink-arg=-O3\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-mtune=native\\", \\"-Clink-arg=-falign-functions=32\\", \\"-Clink-arg=-fasynchronous-unwind-tables\\", \\"-Clink-arg=-funroll-loops\\", \\"-Clink-arg=-fvisibility-inlines-hidden\\", \\"-Clink-arg=-static-libstdc++\\", \\"-Clink-arg=-march=native\\", \\"-Clink-arg=-static-libgcc\\", \\"-Clink-arg=-pthread\\", \\"-Clink-arg=-lpthread\\", \\"-Clink-arg=-L.\\"]\\n[net]\\ngit-fetch-with-cli = true\\n[profile.release]\\nopt-level = 3\\nlto = \\"fat\\"\\n\" > $HOME/.cargo/config.toml\n')
            self._write_strip("unset CFLAGS")
            self._write_strip("unset CXXFLAGS")
            self._write_strip("unset FCFLAGS")
            self._write_strip("unset FFLAGS")
            self._write_strip("unset CFFLAGS")
            self._write_strip("unset LDFLAGS")
            self._write_strip("export CARGO_NET_GIT_FETCH_WITH_CLI=true")
            self._write_strip("export CARGO_PROFILE_RELEASE_LTO=fat")
            self._write_strip("export CARGO_PROFILE_RELEASE_OPT_LEVEL=3")
            self._write_strip("export CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=clang")
            self._write_strip("export SSL_CERT_FILE=/var/cache/ca-certs/anchors/ca-certificates.crt")
            self._write_strip("export CARGO_HTTP_CAINFO=/var/cache/ca-certs/anchors/ca-certificates.crt")
            self._write_strip("export CARGO_TARGET_DIR=target")
            # self._write_strip('export RUSTFLAGS="-Ctarget-cpu=native -Ztune-cpu=native -Cprefer-dynamic=no -Copt-level=3 -Clto=fat -Clinker-plugin-lto -Cembed-bitcode=yes -Clinker=clang -Clink-arg=-flto -Clink-arg=-fuse-ld=lld -Clink-arg=-Wl,--lto-O3 -Clink-arg=-Wl,-O2 -Clink-arg=-Wl,--hash-style=gnu -Clink-arg=-Wl,--enable-new-dtags -Clink-arg=-Wl,--build-id=sha1 -Clink-arg=-fno-stack-protector -Clink-arg=-Wl,--as-needed -Clink-arg=-O3 -Clink-arg=-march=native -Clink-arg=-mtune=native -Clink-arg=-falign-functions=32 -Clink-arg=-fasynchronous-unwind-tables -Clink-arg=-funroll-loops -Clink-arg=-fvisibility-inlines-hidden -Clink-arg=-static-libstdc++ -Clink-arg=-march=native -Clink-arg=-static-libgcc -Clink-arg=-pthread -Clink-arg=-lpthread -Clink-arg=-L."')
            if self.config.install_macro:
                self._write_strip("## install_macro start")
                for line in self.config.install_macro:
                    self._write("{}\n".format(line))
                self._write_strip("## install_macro end")
            else:
                if self.config.config_opts["altcargo1_lto"]:
                    self._write_strip('cargo install %{{?_smp_mflags}} --all-features --offline --no-track --target x86_64-unknown-linux-gnu --verbose --path . --target-dir target --root %{{buildroot}}/usr/ {0} {1}'.format(self.config.extra_configure, self.config.extra_make_install))
                else:
                    self._write_strip('cargo install %{{?_smp_mflags}} --all-features --offline --no-track --verbose --path . --target-dir target --root %{{buildroot}}/usr/ {0} {1}'.format(self.config.extra_configure, self.config.extra_make_install))
        else:
            self.write_prep()
            src_dir = "/usr/share/rust/src/{0}".format(self.name)
            self._write_strip("%build")
            self.write_build_prepend()
            self.write_proxy_exports()
            self._write_strip("mkdir .cargo")
            self._write("echo \"[source.crates-io]\nreplace-with = 'vendored-sources'\n[source.vendored-sources]\ndirectory = '{}'\" > .cargo/config\n".format(os.path.dirname(src_dir)))
            self._write_strip('echo \'{"files":{},"package":""}\' > .cargo-checksum.json')
            # Don't let cargo get outside
            self._write_strip("export http_proxy=http://127.0.0.1:9/")
            self._write_strip("export https_proxy=http://127.0.0.1:9/")
            self._write_strip("export no_proxy=localhost,127.0.0.1,0.0.0.0")
            self._write_strip("cargo build --release")
            self.write_build_append()
            self._write_strip("\n")
            self._write_strip("%install")
            self.write_install_prepend()
            if self.requirements.cargo_bin:
                self._write_strip("cargo install --no-track --all-features --release --root /")
            self._write_strip("cargo clean")
            self._write_strip("install -d -p %{buildroot}" + src_dir)
            self._write_strip("cp -a . %{buildroot}" + src_dir)

    def write_cpan_pattern(self):
        """Write cpan build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("export LANG=C.UTF-8")
        self._write_strip("if test -f Makefile.PL; then")
        self._write_strip("%{__perl} Makefile.PL")
        self.write_make_line()
        self._write_strip("else")
        self._write_strip("%{__perl} Build.PL")
        self._write_strip("./Build")
        self._write_strip("fi")
        self.write_build_append()
        self._write_strip("\n")
        self.write_check()
        self._write_strip("%install")
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self.write_license_files()
        self._write_strip("if test -f Makefile.PL; then")
        self._write_strip("make pure_install PERL_INSTALL_ROOT=%{buildroot} INSTALLDIRS=vendor " + self.config.extra_make_install)
        self._write_strip("else")
        self._write_strip("./Build install --installdirs=vendor --destdir=%{buildroot} " + self.config.extra_make_install)
        self._write_strip("fi")
        self._write_strip("find %{buildroot} -type f -name .packlist -exec rm -f {} ';'")
        self._write_strip("find %{buildroot} -depth -type d -exec rmdir {} 2>/dev/null ';'")
        self._write_strip("find %{buildroot} -type f -name '*.bs' -empty -exec rm -f {} ';'")
        self._write_strip("%{_fixperms} %{buildroot}/*")
        self.write_find_lang()

    def write_scons_pattern(self):
        """Write scons build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("export LANG=C.UTF-8")
        self.write_variables()
        self._write_strip("%scons_config O=3 V=1 VERBOSE=1 {}".format(self.config.extra_configure))
        self.write_make_prepend()
        self.write_trystatic()
        self._write_strip("scons {} O=3 V=1 VERBOSE=1 {}".format(self.config.parallel_build, self.config.extra_make))
        self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self.write_license_files()
        self.write_variables()
        self._write_strip("%scons_install O=3 V=1 VERBOSE=1 {}".format(self.config.extra_make_install))
        self.write_find_lang()

    def write_golang_pattern(self):
        """Write build pattern for go packages."""
        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("export LANG=C.UTF-8")
        if self.config.set_gopath:
            self._write_strip('export GOPATH="$PWD"')
            self._write_strip("go build {}".format(self.config.extra_make))
        else:
            self._write_strip("export GOPROXY=file:///usr/share/goproxy")
            self._write_strip("go mod vendor")
            self._write_strip("go build -mod=vendor {}".format(self.config.extra_make))
        self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self._write_strip("rm -rf %{buildroot}")
        self.write_install_prepend()
        self.write_license_files()
        self._write_strip("\n")

    def write_godep_pattern(self):
        """Write godep build pattern to spec file."""
        self.write_prep()
        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("rm -fr %{buildroot}")
        # Remove golang default proxy prefix and filename to get proxy path for the install
        proxy_path = os.path.join("%{buildroot}/usr/share/goproxy", os.path.dirname(self.url[len("https://proxy.golang.org/") :]))
        self._write_strip(f"mkdir -p {proxy_path}")
        list_file = os.path.join(proxy_path, "list")
        self._write_strip("# Create list file using packaged versions")
        for ver in list(self.content.multi_version.keys()):
            self._write_strip(f"echo {ver} >> {list_file}")
        for idx, source in enumerate(sorted(self.config.sources["godep"])):
            file_path = os.path.join(proxy_path, os.path.basename(source))
            self._write_strip(f"install -m 0644 %{{SOURCE{idx+1}}} {file_path}")
        self._write_strip("\n")

    def write_ant_pattern(self):
        """Write ant build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_proxy_exports()
        self._write_strip("export ANT_HOME=/usr/share/ant")
        for prefix in self.build_dirs.values():
            self._write_strip("cd ../{}\n".format(prefix))
            self.write_build_prepend()
            self._write_strip("ant -d -v " + self.config.extra_make)
            self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("")

    def write_gradle_pattern(self):
        """Write gradle build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_proxy_exports()
        self._write_strip("mkdir -p %{buildroot}")

        # Copy M2 repo contents from buildreqs to Maven's default location.
        # It's ok if this doesn't exist.
        self._write_strip("mkdir -p ~/.m2")
        self._write_strip("cp -r /usr/share/java/.m2/* ~/.m2/ || :")

        for prefix in self.build_dirs.values():
            self._write_strip("cd ../{}\n".format(prefix))

            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)

            self.write_build_prepend()

            # Point to our local maven repo, first
            # style check does not like the escapes here
            self._write_strip(r"find . -type f '(' -name '*.gradle' -o -name '*.gradle.kts' ')' -exec sed -i 's|\(repositories\s*{\)|\1\n    mavenLocal()|' {} +")

            # Opportunistically report detected dependencies
            self._write_strip("gradle --offline dependencies || :")

            # Execute the build goal -- but user must provide it in make_args
            self._write_strip("gradle --offline " + self.config.extra_make)

            self.write_build_append()

            if self.config.subdir:
                self._write_strip("popd")

        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("")
        self.write_gradle_install()

    def write_maven_pattern(self):
        """Write maven build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_proxy_exports()
        self._write_strip("mkdir -p %{buildroot}")
        # It's ok if this doesn't exist
        self._write_strip("mkdir -p ~/.m2")
        self._write_strip("cp -r /usr/share/java/.m2/* ~/.m2/ || :")
        for prefix in self.build_dirs.values():
            self._write_strip("cd ../{}\n".format(prefix))
            self.write_build_prepend()
            self._write_strip("mvn --offline package " + self.config.extra_make)
            self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("")
        self.write_maven_install()

    def write_mvnbin_pattern(self):
        """Write maven build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self.write_mvnbin_install()

    def write_meson_pattern(self):
        """Write meson build pattern to spec file."""
        self.write_prep()
        self.write_lang_c(export_epoch=True)
        self.write_build_prepend()
        if self.config.profile_payload and self.config.config_opts["altflags_pgo"] and not self.config.config_opts["fsalt1"]:
            self.write_variables()
            init = f"{self.get_profile_generate_flags()}"
            post = f"{self.get_profile_use_flags()}"
            self._write_strip("if [ ! -f statuspgo ]; then")
            self._write_strip("echo PGO Phase 1")
            if init:
                self._write_strip(init)
            self.write_build_append()
            if self.config.configure_macro:
                if self.config.subdir:
                    self._write_strip("pushd " + self.config.subdir)
                for line in self.config.configure_macro:
                    self._write("{}\n".format(line))
                self.write_trystatic()
                self.write_make_prepend(build32=False)
                if self.config.make_macro:
                    self._write_strip("## make_macro start")
                    for line in self.config.make_macro:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro end")
                else:
                    self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                    self._write_strip("\n")
                self.write_profile_payload_content(pattern="meson", build_type=None)
                if self.config.custom_clean_pgo:
                    self._write_strip("{}\n".format(self.config.custom_clean_pgo))
                else:
                    self._write_strip("\nfind builddir/ -type f,l -not -name '*.gcno' -not -name 'statuspgo*' -delete -print || :\n")
                self._write_strip("echo USED > statuspgo")
                self._write_strip("fi")
                self._write_strip("if [ -f statuspgo ]; then")
                self._write_strip("echo PGO Phase 2\n")
                self.write_variables()
                if post:
                    self._write_strip(post)
                if self.config.configure_macro_pgo:
                    for line in self.config.configure_macro_pgo:
                        self._write("{}\n".format(line))
                else:
                    for line in self.config.configure_macro:
                        self._write("{}\n".format(line))
                self.write_trystatic()
                self.write_make_prepend(build32=False)
                if self.config.make_macro_pgo:
                    self._write_strip("## make_macro_pgo start")
                    for line in self.config.make_macro_pgo:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro_pgo end")
                elif self.config.make_macro:
                    self._write_strip("## make_macro start")
                    for line in self.config.make_macro:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro end")
                else:
                    self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                self._write_strip("fi")
                self._write_strip("\n")
                if self.config.subdir:
                    self._write_strip("popd")
            else:
                self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} {1} builddir'.format(self.config.extra_configure, self.config.extra_configure64))
                self.write_trystatic()
                self.write_make_prepend(build32=False)
                if self.config.make_macro:
                    self._write_strip("## make_macro start")
                    for line in self.config.make_macro:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro end")
                else:
                    self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                self._write_strip("\n")
                self.write_profile_payload_content(pattern="meson", build_type=None)
                if self.config.custom_clean_pgo:
                    self._write_strip("{}\n".format(self.config.custom_clean_pgo))
                else:
                    self._write_strip("\nfind builddir/ -type f,l -not -name '*.gcno' -not -name 'statuspgo*' -delete -print  || :\n")
                self._write_strip("echo USED > statuspgo")
                self._write_strip("fi")
                self._write_strip("if [ -f statuspgo ]; then")
                self._write_strip("echo PGO Phase 2\n")
                if post:
                    self._write_strip(post)
                if self.config.extra_configure_pgo or self.config.extra_configure64_pgo:
                    self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} {1} builddir'.format(self.config.extra_configure_pgo, self.config.extra_configure64_pgo))
                elif self.config.extra_configure or self.config.extra_configure64:
                    self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} {1} builddir'.format(self.config.extra_configure, self.config.extra_configure64))
                self.write_trystatic()
                self.write_make_prepend(build32=False)
                if self.config.make_macro_pgo:
                    self._write_strip("## make_macro_pgo start")
                    for line in self.config.make_macro_pgo:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro_pgo end")
                elif self.config.make_macro:
                    self._write_strip("## make_macro start")
                    for line in self.config.make_macro:
                        self._write("{}\n".format(line))
                    self._write_strip("## make_macro end")
                else:
                    self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                self._write_strip("fi")
                self._write_strip("\n")
                if self.config.subdir:
                    self._write_strip("popd")

            if self.config.config_opts["build_special"]:
                self.write_variables()
                self._write_strip("pushd ../build-special/" + self.config.subdir)
                init = f"{self.get_profile_generate_flags()}"
                post = f"{self.get_profile_use_flags()}"
                self._write_strip("if [ ! -f statuspgo ]; then")
                self._write_strip("echo PGO Phase 1")
                if init:
                    self._write_strip(init)
                self.write_build_append()
                if self.config.configure_macro_special:
                    for line in self.config.configure_macro_special:
                        self._write("{}\n".format(line))
                    self.write_trystatic()
                    self.write_make_prepend(build32=False)
                    if self.config.make_macro_special:
                        self._write_strip("## make_macro_special start")
                        for line in self.config.make_macro_special:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro_special end")
                    else:
                        self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                        self._write_strip("\n")
                    self.write_profile_payload_content(pattern="meson", build_type="special")
                    if self.config.custom_clean_pgo:
                        self._write_strip("{}\n".format(self.config.custom_clean_pgo))
                    else:
                        self._write_strip("\nfind builddir/ -type f,l -not -name '*.gcno' -not -name 'statuspgo*' -delete -print || :\n")
                    self._write_strip("echo USED > statuspgo")
                    self._write_strip("fi")
                    self._write_strip("if [ -f statuspgo ]; then")
                    self._write_strip("echo PGO Phase 2\n")
                    self.write_variables()
                    if post:
                        self._write_strip(post)
                    if self.config.configure_macro_special_pgo:
                        for line in self.config.configure_macro_special_pgo:
                            self._write("{}\n".format(line))
                    else:
                        for line in self.config.configure_macro_special:
                            self._write("{}\n".format(line))
                    self.write_trystatic()
                    self.write_make_prepend(build32=False)
                    if self.config.make_macro_special_pgo:
                        self._write_strip("## make_macro_special_pgo start")
                        for line in self.config.make_macro_special_pgo:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro_special_pgo end")
                    elif self.config.make_macro_special:
                        self._write_strip("## make_macro_special start")
                        for line in self.config.make_macro_special:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro_special end")
                    else:
                        self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                    self._write_strip("fi")
                    self._write_strip("\n")
                    if self.config.subdir:
                        self._write_strip("popd")
                else:
                    self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} builddir'.format(self.config.extra_configure_special))
                    self.write_trystatic()
                    self.write_make_prepend(build32=False)
                    if self.config.make_macro_special:
                        self._write_strip("## make_macro_special start")
                        for line in self.config.make_macro_special:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro_special end")
                    elif self.config.make_macro:
                        self._write_strip("## make_macro start")
                        for line in self.config.make_macro:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro end")
                    else:
                        self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                        self._write_strip("\n")
                    self.write_profile_payload_content(pattern="meson", build_type="special")
                    if self.config.custom_clean_pgo:
                        self._write_strip("{}\n".format(self.config.custom_clean_pgo))
                    else:
                        self._write_strip("\nfind builddir/ -type f,l -not -name '*.gcno' -not -name 'statuspgo*' -delete -print  || :\n")
                    self._write_strip("echo USED > statuspgo")
                    self._write_strip("fi")
                    self._write_strip("if [ -f statuspgo ]; then")
                    self._write_strip("echo PGO Phase 2\n")
                    if post:
                        self._write_strip(post)
                    if self.config.extra_configure_special_pgo:
                        self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} builddir'.format(self.config.extra_configure_special_pgo))
                    elif self.config.extra_configure_special:
                        self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} builddir'.format(self.config.extra_configure_special))
                    self.write_trystatic()
                    self.write_make_prepend(build32=False)
                    if self.config.make_macro_special_pgo:
                        self._write_strip("## make_macro_special_pgo start")
                        for line in self.config.make_macro_special_pgo:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro_special_pgo end")
                    elif self.config.make_macro_special:
                        self._write_strip("## make_macro_special start")
                        for line in self.config.make_macro_special:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro_special end")
                    elif self.config.make_macro:
                        self._write_strip("## make_macro start")
                        for line in self.config.make_macro:
                            self._write("{}\n".format(line))
                        self._write_strip("## make_macro end")
                    else:
                        self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                    self._write_strip("fi")
                    self._write_strip("\n")
                    if self.config.subdir:
                        self._write_strip("popd")
        else:
            self.write_variables()
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib64 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} {1} builddir'.format(self.config.extra_configure, self.config.extra_configure64))
            self.write_trystatic()
            self.write_make_prepend(build32=False)
            if self.config.make_macro:
                self._write_strip("## make_macro start")
                for line in self.config.make_macro:
                    self._write("{}\n".format(line))
                self._write_strip("## make_macro end")
            else:
                self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
                self._write_strip("\n")
            if self.config.subdir:
                self._write_strip("popd")

        if self.config.config_opts["use_avx2"]:
            self._write_strip('CFLAGS="$CFLAGS -m64 -march=native -mtune=native" CXXFLAGS="$CXXFLAGS -m64 -march=native -mtune=native" LDFLAGS="$LDFLAGS -m64 -march=native -mtune=native" meson --libdir=lib64/haswell --prefix=/usr --buildtype=plain -Ddefault_library=both {0} {1} builddiravx2'.format(self.config.extra_configure, self.config.extra_configure64))
            self.write_trystatic()
            self.write_make_prepend(build32=False)
            self._write_strip("ninja --verbose %{?_smp_mflags} -C builddiravx2")
            if self.config.config_opts['use_avx512']:
                self._write_strip('CFLAGS="$CFLAGS -m64 -march=skylake-avx512" CXXFLAGS="$CXXFLAGS -m64 -march=skylake-avx512" LDFLAGS="$LDFLAGS -m64 -march=skylake-avx512" meson --libdir=lib64/haswell/avx512_1 --prefix=/usr --buildtype=plain {0} {1} builddiravx512'.format(self.config.extra_configure, self.config.extra_configure64))
                self._write_strip('ninja -v -C builddiravx512')
                if self.config.subdir:
                    self._write_strip("popd")
        if self.config.config_opts["32bit"]:
            self._write_strip("pushd ../build32/" + self.config.subdir)
            self.write_build_prepend32()
            self.write_32bit_exports()
            self.write_build_append()
            self._write_strip('CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS" LDFLAGS="$LDFLAGS" meson --libdir=lib32 --prefix=/usr --buildtype=plain -Ddefault_library=both {0} {1} builddir'.format(self.config.extra_configure, self.config.extra_configure32))
            self.write_trystatic()
            self.write_make_prepend(build32=True)
            self._write_strip("ninja --verbose %{?_smp_mflags} -C builddir")
            self._write_strip("popd")

        self.write_build_append()
        self._write_strip("\n")
        self.write_check()
        self._write_strip("%install")
        self.write_install_prepend()
        self.write_license_files()
        if self.config.config_opts["32bit"]:
            self._write_strip("pushd ../build32/" + self.config.subdir)
            self._write_strip("DESTDIR=%{buildroot} ninja -C builddir install")
            self._write_strip("if [ -d  %{buildroot}/usr/lib32/pkgconfig ]")
            self._write_strip("then")
            self._write_strip("    pushd %{buildroot}/usr/lib32/pkgconfig\n")
            self._write_strip("    for i in *.pc ; do ln -s $i 32$i ; done")
            self._write_strip("    popd")
            self._write_strip("fi")
            self._write_strip("if [ -d %{buildroot}/usr/share/pkgconfig ]")
            self._write_strip("then")
            self._write_strip("    pushd %{buildroot}/usr/share/pkgconfig")
            self._write_strip("    for i in *.pc ; do ln -s $i 32$i ; done")
            self._write_strip("    popd")
            self._write_strip("fi")
            self._write_strip("popd")
        if self.config.config_opts['use_avx512']:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip('DESTDIR=%{buildroot} ninja -C builddiravx512 install')
            if self.config.subdir:
                self._write_strip("popd")
        if self.config.config_opts["use_avx2"]:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip("DESTDIR=%{buildroot} ninja -C builddiravx2 install")
            if self.config.subdir:
                self._write_strip("popd")
        if self.config.config_opts["build_special"]:
            self._write_strip("pushd ../build-special/" + self.config.subdir)
            self._write_strip("DESTDIR=%{buildroot} ninja -C builddir install")
            self._write_strip("popd")
            if self.config.subdir:
                self._write_strip("popd")
        if self.config.install_macro:
            self._write_strip("## install_macro start")
            for line in self.config.install_macro:
                self._write("{}\n".format(line))
            self._write_strip("## install_macro end")
        else:
            if self.config.subdir:
                self._write_strip("pushd " + self.config.subdir)
            self._write_strip("DESTDIR=%{buildroot} ninja -C builddir install")
            if self.config.subdir:
                self._write_strip("popd")
        self.write_find_lang()

    def write_phpize_pattern(self):
        """Write phpize build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("phpize")
        self._write_strip("%configure {0} {1}"
                          .format(self.config.disable_static,
                                  self.config.extra_configure))
        self.write_make_line()
        self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("%make_install")
        self._write_strip("\n")

    def write_nginx_pattern(self):
        """Write nginx build pattern to spec file."""
        self.write_prep()
        self._write_strip("%build")
        self.write_build_prepend()
        self.write_proxy_exports()
        self._write_strip("nginx-module configure")
        self._write_strip("nginx-module build")
        self.write_build_append()
        self._write_strip("\n")
        self._write_strip("%install")
        self.write_install_prepend()
        self._write_strip("nginx-module install %{buildroot}")
        self._write_strip("\n")

    def write_find_lang(self):
        """Write %find_lang macro to spec file."""
        for lang in self.locales:
            self._write("%find_lang {}\n".format(lang))

    def apply_patches(self):
        """Write patch list to spec file."""
        counter = 1
        for p in self.config.patches:
            name = p.split(None, 1)[0]
            if name == p:
                options = "-p1"
            else:
                options = p.split(None, 1)[1]
            if not p.split()[0].endswith(".nopatch"):
                self._write("%patch{} {}\n".format(counter, options))
            counter = counter + 1

        # Write version-specific patch commands
        for version in self.config.verpatches:
            if self.config.verpatches[version]:
                self._write("cd ../{}\n".format(self.build_dirs[self.config.versions[version]]))
            for p in self.config.verpatches[version]:
                name = p.split(None, 1)[0]
                if name == p:
                    options = "-p1"
                else:
                    options = p.split(None, 1)[1]
                if not p.split()[0].endswith(".nopatch"):
                    self._write("%patch{} {}\n".format(counter, options))
                counter = counter + 1

    def apply_patches_cargo(self):
        """Write patch list for cargo to spec file."""
        prefix_to_remove = f"{self.mock_dir}/clear-{self.content.name}/root"
        target = f"{self.mock_dir}/clear-{self.content.name}/root/builddir/.cargo/registry/src"
        patches_path = f"{self.mock_dir}/clear-{self.content.name}/root/builddir/build/SOURCES".removeprefix(prefix_to_remove)
        pat = re.compile(r"{}-(?:(?:\d+)(?:\.\d+)+)")
        # print(f"target: {target}")
        for count, patch in enumerate(self.config.patches_cargo):
            pat0 = f"{patch[1]}-(?:(?:\d+)(?:\.\d+)+)"
            pat = re.compile(pat0)
            found = False
            for dirpath, dirnames, filenames in os.walk(target, followlinks=True):
                if found == True:
                    break
                else:
                    for dirname in dirnames:
                        if pat.search(dirname):
                            # print(f"found: {dirname} in {dirpath}")
                            # print(f"found: {os.path.join(dirpath, dirname).removeprefix(prefix_to_remove)}")
                            self._write_strip(f"pushd {os.path.join(dirpath, dirname).removeprefix(prefix_to_remove)}")
                            self._write_strip(f"patch --no-backup-if-mismatch --fuzz=2 --strip=1 < {patches_path}/{patch[0]}")
                            self._write_strip(f"popd")
                            found = True
                            break

    def _write(self, string):
        self.specfile.write(string)

    def _write_strip(self, string):
        self.specfile.write_strip(string)

    def quote_filename(self, filename):
        """Quotes the filename, if necessary. Identifies and skips any RPM directive prefix."""
        # Characters that require quoting -- only those with special
        # meaning in specfiles
        special_chars = set(" \t")
        # Build up the output as a string
        quoted = ""
        # Capture any directive prefix separately from actual filename
        #                          (1                   )(3 )
        directive_re = re.compile(r"(%\w+(\([^\)]*\))?\s+)(.*)")
        parts = directive_re.match(filename)
        if parts:
            # Add prefix to the output
            quoted += parts.group(1)
            # Set the filename to the remaining portion
            filename = parts.group(3)

        # Now check for special characters
        if any(c in filename for c in special_chars):
            # Quote the filename
            quoted += '"{}"'.format(filename)
        else:
            # Add the filename as-is
            quoted += filename
        return quoted
