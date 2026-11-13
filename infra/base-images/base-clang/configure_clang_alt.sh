#!/bin/bash
set -eu

# Chromium's bootstrap Clang does not discover ALT's GCC installation layout.
# Use GCC itself to locate its startup objects and libraries. Keep this in the
# default driver config so CMake's nested runtime builds and subsequent project
# builds get the same setting without having to propagate CFLAGS everywhere.
compiler_bin_dir="$1"
gcc32_install_dir="${2:-}"
gcc_install_dir=$(dirname "$(gcc -print-libgcc-file-name)")
test -f "${gcc_install_dir}/crtbeginS.o"
for driver in clang clang++; do
  printf '%s\n' "--gcc-install-dir=${gcc_install_dir}" > "${compiler_bin_dir}/${driver}.cfg"
done

# ALT ships i586 GCC separately, not as a /32 multilib of its x86_64 GCC.
# A target-specific config takes precedence over clang.cfg for -m32 builds.
if [ -n "$gcc32_install_dir" ]; then
  test -f "${gcc32_install_dir}/crtbeginS.o"
  triple32=$("${compiler_bin_dir}/clang" --no-default-config -m32 -print-target-triple)
  for driver in clang clang++; do
    printf '%s\n' "--gcc-install-dir=${gcc32_install_dir}" > "${compiler_bin_dir}/${triple32}-${driver}.cfg"
  done
fi
