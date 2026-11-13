FROM ghcr.io/fobos-nt/fuzz-manager/base-builder

# get the source code of json-parser v1.1.0
RUN git clone https://github.com/json-parser/json-parser

WORKDIR json-parser
COPY build.sh $SRC/
COPY assets $SRC/assets
