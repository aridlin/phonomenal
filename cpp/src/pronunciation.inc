#include "espeak_ipa.inc"

// Native eSpeak NG pronunciation only. Audio always comes from the selected
// pack.
std::vector<std::string> NativePronunciation(const std::string &word) {
  using Init = int (*)(int, int, const char *, int);
  using Voice = int (*)(const char *);
  using Phones = const char *(*)(const void **, int, int);
  static std::mutex mutex;
  std::lock_guard guard(mutex);
  static Init initialize = nullptr;
  static Voice voice = nullptr;
  static Phones phones = nullptr;
  static bool attempted = false, ready = false;
  if (!attempted) {
    attempted = true;
#ifdef _WIN32
    auto module = LoadLibraryW(L"libespeak-ng.dll");
    if (!module)
      module = LoadLibraryW(L"espeak-ng.dll");
    if (module) {
      initialize =
          reinterpret_cast<Init>(GetProcAddress(module, "espeak_Initialize"));
      voice = reinterpret_cast<Voice>(
          GetProcAddress(module, "espeak_SetVoiceByName"));
      phones = reinterpret_cast<Phones>(
          GetProcAddress(module, "espeak_TextToPhonemes"));
    }
#else
    auto module = dlopen("libespeak-ng.so.1", RTLD_NOW | RTLD_LOCAL);
    if (module) {
      initialize = reinterpret_cast<Init>(dlsym(module, "espeak_Initialize"));
      voice = reinterpret_cast<Voice>(dlsym(module, "espeak_SetVoiceByName"));
      phones = reinterpret_cast<Phones>(dlsym(module, "espeak_TextToPhonemes"));
    }
#endif
    ready = initialize && voice && phones && initialize(2, 0, nullptr, 0) > 0;
  }
  if (!ready || voice("en-us") != 0)
    return {};
  const void *ptr = word.c_str();
  const char *raw = phones(&ptr, 1, ('|' << 8) | 2);
  if (!raw)
    return {};
  return ParseEspeakIpa(raw);
}
