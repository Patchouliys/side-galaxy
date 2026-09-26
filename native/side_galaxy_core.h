#ifndef SIDE_GALAXY_CORE_H
#define SIDE_GALAXY_CORE_H

#if defined(_WIN32)
#  if defined(SG_CORE_BUILD)
#    define SG_CORE_API __declspec(dllexport)
#  else
#    define SG_CORE_API __declspec(dllimport)
#  endif
#else
#  define SG_CORE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* The caller owns the returned UTF-8 JSON buffer and must release it with sg_core_free.
 * A null result means allocation failed. No exceptions cross this C boundary.
 * Each call opens its own SQLite connection and commits one immediate transaction. */
SG_CORE_API int sg_core_abi_version(void);
SG_CORE_API char* sg_core_call(const char* db_path, const char* operation, const char* payload_json);
SG_CORE_API void sg_core_free(char* result);

#ifdef __cplusplus
}
#endif
#endif
