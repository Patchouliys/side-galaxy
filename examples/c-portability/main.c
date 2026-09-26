#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/utsname.h>

static void json_string(FILE *stream, const char *text) {
    fputc('"', stream);
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p == '"' || *p == '\\') fprintf(stream, "\\%c", *p);
        else if (*p < 32) fprintf(stream, "\\u%04x", *p);
        else fputc(*p, stream);
    }
    fputc('"', stream);
}

static void report(FILE *stream, const struct utsname *system, long iterations, uint64_t checksum) {
    fputs("{\"os\":", stream);
    json_string(stream, system->sysname);
    fputs(",\"machine\":", stream);
    json_string(stream, system->machine);
    fputs(",\"compiler\":", stream);
    json_string(stream, __VERSION__);
    fprintf(stream, ",\"pointer_bits\":%zu,\"iterations\":%ld,\"checksum\":\"%016" PRIx64 "\"}\n",
            sizeof(void *) * 8, iterations, checksum);
}

int main(int argc, char **argv) {
    long iterations = 10000;
    if (argc != 1) {
        char *end = NULL;
        if (argc != 3 || strcmp(argv[1], "--iterations") != 0) {
            fputs("usage: portability-check [--iterations 1..1000000]\n", stderr);
            return 2;
        }
        errno = 0;
        iterations = strtol(argv[2], &end, 10);
        if (errno || !end || *end || iterations < 1 || iterations > 1000000) {
            fputs("invalid iteration count\n", stderr);
            return 2;
        }
    }
    struct utsname system;
    if (uname(&system) != 0) { perror("uname"); return 1; }
    uint64_t checksum = UINT64_C(1469598103934665603);
    for (long i = 0; i < iterations; ++i) {
        checksum ^= (uint64_t)i;
        checksum *= UINT64_C(1099511628211);
    }
    FILE *output = fopen("result.json", "w");
    if (!output) { perror("result.json"); return 1; }
    report(output, &system, iterations, checksum);
    if (fclose(output) != 0) { perror("fclose"); return 1; }
    report(stdout, &system, iterations, checksum);
    return 0;
}
