#!/bin/bash -eux
# Copyright 2022 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
################################################################################

# Install base-builder's dependencies in a architecture-aware way.

if [ -f /etc/altlinux-release ]; then
  apt-get update
  apt-get install -y binutils-devel gcc gcc-c++ make curl wget git jq \
      patchelf rsync subversion zip unzip tar xz pkg-config
  if [ "$(uname -m)" = x86_64 ]; then
    apt-get install -y i586-glibc-devel.32bit i586-libgcc1.32bit
  fi
  exit 0
fi

case $(uname -m) in
    x86_64)
	dpkg --add-architecture i386
        ;;
esac

apt-get update && \
    apt-get install -y \
        binutils-dev \
        build-essential \
        curl \
        wget \
        git \
        jq \
        patchelf \
        rsync \
        subversion \
        zip

case $(uname -m) in
    x86_64)
	apt-get install -y libc6-dev-i386
        ;;
esac
