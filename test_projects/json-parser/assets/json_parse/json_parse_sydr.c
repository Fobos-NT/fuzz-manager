#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>


int main(int argc, char** argv)
{
  FILE* fd = fopen(argv[1], "rb");
  if (!fd) return 1;
  fseek(fd, 0, SEEK_END);
  long fsize = ftell(fd);
  fseek(fd, 0, SEEK_SET);
  char* buffer = (char*)malloc(fsize);
  fread(buffer, 1, fsize, fd);
  fclose(fd);
  return LLVMFuzzerTestOneInput((const uint8_t*)buffer, fsize);
}