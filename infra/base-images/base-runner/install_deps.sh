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

# Install dependencies in a platform-aware way.

if [ -f /etc/altlinux-release ]; then
  source /etc/os-release
  SSL_PACKAGE=libssl1.1
  if [ "${ALT_BRANCH_ID:-}" = p11 ]; then
    SSL_PACKAGE=libssl3
  fi
  apt-get update
  apt-get install -y binutils file ca-certificates fonts-ttf-dejavu git \
      libcap rsync unzip jq wget zip curl tar xz perl-Digest-SHA \
      zlib libncurses libgdbm libnss "$SSL_PACKAGE" libsqlite3 libreadline-devel libffi \
      bzlib liblzma libyaml2 libstdc++6 libatomic1
  if [ "$(uname -m)" = x86_64 ]; then
    apt-get install -y i586-libgcc1.32bit i586-glibc-core.32bit
  fi
  exit 0
fi

apt-get update && apt-get install -y \
    binutils \
    file \
    ca-certificates \
    fonts-dejavu \
    git \
    libcap2 \
    rsync \
    unzip \
    jq \
    wget \
    zip --no-install-recommends

case $(uname -m) in
  x86_64)
    # We only need to worry about i386 if we are on x86_64.
    apt-get install -y lib32gcc1 libc6-i386
    ;;
esac
