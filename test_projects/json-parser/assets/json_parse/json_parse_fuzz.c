#include <stdio.h>
#include <unistd.h>
#include "json.h"


int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    json_char* json;
    json_value* value;

    json = (json_char*)data;
    value = json_parse(json, size);
    if (value == NULL) {
        return 1;
    }

    json_value_free(value);
    return 0;
}
