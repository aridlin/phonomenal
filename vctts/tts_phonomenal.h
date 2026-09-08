#pragma once

#include <cstdint>
#include <filesystem>
#include <string>
#include <vector>

namespace tts_phonomenal {

struct SpeakResult {
    std::vector<std::uint8_t> audio;
    std::wstring error;
    std::wstring status;
};

std::vector<std::wstring> list_voice_labels(const std::filesystem::path& directory = {});
std::wstring voice_id_for_index(int index);
std::filesystem::path discover_bank_directory();
std::filesystem::path bank_path_for_index(const std::filesystem::path& bank_directory, int index);
bool bank_exists_for_index(const std::filesystem::path& bank_directory, int index);
int available_bank_count(const std::filesystem::path& bank_directory);
SpeakResult speak_wav(const std::wstring& text, const std::filesystem::path& bank_path);

}  // namespace tts_phonomenal
