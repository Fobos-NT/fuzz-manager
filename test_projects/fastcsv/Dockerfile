
FROM ghcr.io/fobos-nt/fuzz-manager/base-builder-jvm

RUN apt update && apt install -y openjdk-17-jdk

RUN git clone --depth 1 https://github.com/google/fuzzing && \
    mv fuzzing/dictionaries/csv.dict $SRC/csv.dict && \
    rm -rf fuzzing

RUN git clone --depth 1 https://github.com/dvyukov/go-fuzz-corpus && \
    zip -j $SRC/CsvReaderFuzzer_seed_corpus.zip go-fuzz-corpus/csv/corpus/* && \
    rm -rf go-fuzz-corpus

RUN git clone --depth 1 https://github.com/osiegmar/FastCSV.git fastcsv

WORKDIR fastcsv
COPY build.sh $SRC/
COPY assets/* $SRC/