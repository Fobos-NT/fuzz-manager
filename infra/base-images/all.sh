#!/bin/bash -eux
# Copyright 2016 Google Inc.
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

set -e

GHCR_REGISTRY="${GHCR_REGISTRY:-ghcr.io/fobos-nt/fuzz-manager}"
ALT_C10F2_IMAGE="${ALT_C10F2_IMAGE:-registry.altlinux.org/c10f/alt:20261014}"
ALT_P11_IMAGE="${ALT_P11_IMAGE:-registry.altlinux.org/p11/alt:20261014}"
# Each variant builds the complete dependency-ordered image matrix.
BASE_VARIANTS="${BASE_VARIANTS:-latest alt-c10f2 alt-p11}"
PUSH_IMAGES="${PUSH_IMAGES:-0}"

# Все дополнительные аргументы, переданные скрипту.
# Например:
#   ./build-base-images.sh --no-cache
#   ./build-base-images.sh --build-arg FOO=bar
BUILD_ARGS=("$@")

build_base_image() {
    local image_name="$1"
    local context="$2"
    local variant="$3"
    local dockerfile="${context}/Dockerfile"
    local variant_args=()
    local output_args=(--load)
    local cache_tag=cache

    if [[ "$variant" == alt-* ]]; then
        cache_tag="cache-${variant}"
        variant_args+=(--build-arg "BASE_REGISTRY=${GHCR_REGISTRY}"
                       --build-arg "BASE_TAG=${variant}")
        if [[ "$image_name" == base-image ]]; then
            dockerfile="${context}/alt.Dockerfile"
            case "$variant" in
                alt-c10f2) variant_args+=(--build-arg "parent_image=${ALT_C10F2_IMAGE}") ;;
                alt-p11) variant_args+=(--build-arg "parent_image=${ALT_P11_IMAGE}") ;;
            esac
        fi
    fi

    echo "========================================"
    echo "Building ${image_name}:${variant}"
    echo "========================================"

    docker buildx build \
        -f "${dockerfile}" \
        -t "${GHCR_REGISTRY}/${image_name}:${variant}" \
        "${output_args[@]}" \
        "${BUILD_ARGS[@]}" \
        "${variant_args[@]}" \
        "${context}"

    echo "========================================"
    echo "Successfully built ${image_name}:${variant}"
    echo "GHCR:   ${GHCR_REGISTRY}/${image_name}:${variant}"
    echo "========================================"
    echo
}

# Validate the complete selection before building or publishing anything.
for variant in $BASE_VARIANTS; do
    case "$variant" in
        latest|alt-c10f2|alt-p11) ;;
        *) echo "Unsupported base variant: ${variant}" >&2; exit 1 ;;
    esac
done

for variant in $BASE_VARIANTS; do
    images=(base-image base-clang base-builder base-builder-go
            base-builder-jvm base-builder-python base-builder-rust
            base-builder-ruby base-builder-swift base-runner base-runner-debug)
    for image in "${images[@]}"; do
        build_base_image "$image" "infra/base-images/${image}" "$variant"
    done
done
