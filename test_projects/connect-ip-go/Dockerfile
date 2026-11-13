FROM ghcr.io/fobos-nt/fuzz-manager/base-builder-go

RUN go install github.com/AdamKorcz/go-118-fuzz-build@latest

RUN git clone --depth 1 https://github.com/quic-go/connect-ip-go/ $GOPATH/src/github.com/quic-go/connect-ip-go

COPY build.sh $SRC/build.sh
RUN chmod +x $SRC/build.sh