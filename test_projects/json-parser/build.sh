#!/bin/bash -eu

CC=$CC CXX=$CXX CFLAGS=$CFLAGS CXXFLAGS=$CXXFLAGS ./configure
make clean
make libjsonparser.a

$CC $CFLAGS -I$SRC/json-parser $SRC/assets/json_parse/json_parse_fuzz.c -o $OUT/json_parse -lm $LIB_FUZZING_ENGINE $SRC/json-parser/libjsonparser.a

cp -rf $SRC/assets/json_parse/* $OUT/
zip -j $OUT/json_parse_seed_corpus.zip $SRC/assets/json_parse/json_parse_seed_corpus/*