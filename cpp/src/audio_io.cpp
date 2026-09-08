#define MINIAUDIO_IMPLEMENTATION
#include "audio_io.h"
#include "../vendor/miniaudio.h"
#include <algorithm>
#include <cmath>
#include <mutex>
#include <stdexcept>
struct AudioIO::Impl {
  ma_context context{};
  bool context_ok = false, recording = false, playing = false;
  ma_device capture{}, output{};
  ma_decoder decoder{};
  std::vector<ma_device_id> ids;
  std::vector<std::int16_t> samples;
  std::vector<std::uint8_t> playback;
  std::mutex mutex;
  std::atomic<float> peak{0};
  std::atomic<std::size_t> count{0};
  static void captured(ma_device *d, void *, const void *input,
                       ma_uint32 frames) {
    auto &s = *static_cast<Impl *>(d->pUserData);
    if (!input)
      return;
    auto p = static_cast<const std::int16_t *>(input);
    float peak = 0;
    for (ma_uint32 i = 0; i < frames; ++i)
      peak = std::max(peak, std::abs(float(p[i]) / 32768));
    s.peak = peak;
    std::lock_guard guard(s.mutex);
    if (s.samples.size() + frames <= 48000 * 180) {
      s.samples.insert(s.samples.end(), p, p + frames);
      s.count = s.samples.size();
    }
  }
  static void played(ma_device *d, void *out, const void *, ma_uint32 frames) {
    auto &s = *static_cast<Impl *>(d->pUserData);
    ma_uint64 read = 0;
    ma_decoder_read_pcm_frames(&s.decoder, out, frames, &read);
    if (read < frames)
      std::fill_n(static_cast<float *>(out) + read, frames - read, 0.f);
  }
};
AudioIO::AudioIO() : impl(std::make_unique<Impl>()) {}
AudioIO::~AudioIO() {
  stop_record();
  stop_playback();
  if (impl->context_ok)
    ma_context_uninit(&impl->context);
}
std::vector<std::string> AudioIO::capture_devices() {
  std::vector<std::string> names{"Default microphone"};
  if (!impl->context_ok) {
    if (ma_context_init(nullptr, 0, nullptr, &impl->context) != MA_SUCCESS)
      throw std::runtime_error("Cannot initialize audio devices");
    impl->context_ok = true;
  }
  ma_device_info *info = nullptr;
  ma_uint32 count = 0;
  if (ma_context_get_devices(&impl->context, nullptr, nullptr, &info, &count) !=
      MA_SUCCESS)
    throw std::runtime_error("Cannot enumerate microphones");
  impl->ids.clear();
  for (ma_uint32 i = 0; i < count; ++i) {
    names.emplace_back(info[i].name);
    impl->ids.push_back(info[i].id);
  }
  return names;
}
void AudioIO::record(int device_index) {
  stop_record();
  if (!impl->context_ok)
    capture_devices();
  {
    std::lock_guard guard(impl->mutex);
    impl->samples.clear();
    impl->samples.reserve(48000 * 180);
  }
  impl->count = 0;
  impl->peak = 0;
  auto cfg = ma_device_config_init(ma_device_type_capture);
  cfg.capture.format = ma_format_s16;
  cfg.capture.channels = 1;
  cfg.sampleRate = 48000;
  cfg.dataCallback = Impl::captured;
  cfg.pUserData = impl.get();
  if (device_index > 0 &&
      static_cast<std::size_t>(device_index) <= impl->ids.size())
    cfg.capture.pDeviceID =
        &impl->ids[static_cast<std::size_t>(device_index - 1)];
  if (ma_device_init(&impl->context, &cfg, &impl->capture) != MA_SUCCESS)
    throw std::runtime_error("Cannot open selected microphone");
  impl->recording = true;
  if (ma_device_start(&impl->capture) != MA_SUCCESS) {
    stop_record();
    throw std::runtime_error("Cannot start microphone");
  }
}
void AudioIO::stop_record() {
  if (impl->recording) {
    ma_device_uninit(&impl->capture);
    impl->recording = false;
  }
}
void AudioIO::save_recording(const std::filesystem::path &path) {
  stop_record();
  std::lock_guard guard(impl->mutex);
  if (impl->samples.empty())
    throw std::runtime_error("No microphone audio recorded");
  std::filesystem::create_directories(path.parent_path());
  ma_encoder encoder{};
  auto cfg =
      ma_encoder_config_init(ma_encoding_format_wav, ma_format_s16, 1, 48000);
#ifdef _WIN32
  auto rc = ma_encoder_init_file_w(path.c_str(), &cfg, &encoder);
#else
  auto rc = ma_encoder_init_file(path.c_str(), &cfg, &encoder);
#endif
  if (rc != MA_SUCCESS)
    throw std::runtime_error("Cannot save recording");
  ma_uint64 written = 0;
  rc = ma_encoder_write_pcm_frames(&encoder, impl->samples.data(),
                                   impl->samples.size(), &written);
  ma_encoder_uninit(&encoder);
  if (rc != MA_SUCCESS || written != impl->samples.size())
    throw std::runtime_error("Incomplete microphone recording");
}
void AudioIO::play(const std::vector<std::uint8_t> &wav) {
  stop_playback();
  impl->playback = wav;
  auto decoder_cfg = ma_decoder_config_init(ma_format_f32, 1, 48000);
  if (ma_decoder_init_memory(impl->playback.data(), impl->playback.size(),
                             &decoder_cfg, &impl->decoder) != MA_SUCCESS)
    throw std::runtime_error("Invalid WAV playback data");
  auto cfg = ma_device_config_init(ma_device_type_playback);
  cfg.playback.format = ma_format_f32;
  cfg.playback.channels = 1;
  cfg.sampleRate = 48000;
  cfg.dataCallback = Impl::played;
  cfg.pUserData = impl.get();
  if (ma_device_init(nullptr, &cfg, &impl->output) != MA_SUCCESS) {
    ma_decoder_uninit(&impl->decoder);
    throw std::runtime_error("Cannot open playback device");
  }
  impl->playing = true;
  if (ma_device_start(&impl->output) != MA_SUCCESS) {
    stop_playback();
    throw std::runtime_error("Cannot start playback");
  }
}
void AudioIO::stop_playback() {
  if (impl->playing) {
    ma_device_uninit(&impl->output);
    ma_decoder_uninit(&impl->decoder);
    impl->playing = false;
  }
}
float AudioIO::level() const { return impl->peak.load(); }
double AudioIO::seconds() const { return double(impl->count.load()) / 48000; }
