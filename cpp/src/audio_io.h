#pragma once
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
class AudioIO {
public:
    AudioIO();~AudioIO();
    std::vector<std::string> capture_devices();
    void record(int device_index=0);
    void stop_record();
    void save_recording(const std::filesystem::path& path);
    void play(const std::vector<std::uint8_t>& wav);
    void stop_playback();
    float level() const;
    double seconds() const;
private:
    struct Impl;std::unique_ptr<Impl> impl;
};
