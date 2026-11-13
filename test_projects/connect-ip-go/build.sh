#!/bin/bash
set -euo pipefail

exec bash "$GOPATH/src/github.com/quic-go/connect-ip-go/oss-fuzz.sh" "$@"