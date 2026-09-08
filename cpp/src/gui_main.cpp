#define FT_IMPLEMENTATION
#include "audio_io.h"
#include "child_process.h"
#include "ft.hpp"
#include "phonomenal_splicer/splicer.h"
#include <atomic>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iomanip>
#include <memory>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>
namespace fs = std::filesystem;
#include "reading_script.inc"
static std::string utf8(const fs::path &p) {
  auto u = p.u8string();
  return {u.begin(), u.end()};
}
template <std::size_t N>
static void copy(char (&to)[N], const std::string &from) {
  std::snprintf(to, N, "%s", from.c_str());
}
static fs::path path_utf8(const std::string &s) { return fs::path(std::u8string(reinterpret_cast<const char8_t *>(s.data()), s.size())); }
static fs::path find_root(const char *executable) {
  std::vector<fs::path> candidates{fs::current_path(),
                                   fs::absolute(executable).parent_path()};
  for (auto p : candidates)
    for (int i = 0; i < 6; ++i, p = p.parent_path())
      if (fs::exists(p / "scripts/builder.py"))
        return p;
  return fs::current_path();
}
static std::string read_tail(const fs::path &path) {
  std::ifstream f(path);
  if (!f)
    return {};
  f.seekg(0, std::ios::end);
  auto size = f.tellg();
  if (size > 4096)
    f.seekg(size - std::streamoff(4096));
  else
    f.seekg(0);
  return {std::istreambuf_iterator<char>(f), {}};
}
struct App {
  char source[2048]{}, output[2048]{}, voice[128]{}, python[2048]{},
      mfa[2048]{}, pack[2048]{}, prompt[8192]{}, wav_path[2048]{};
  fs::path root, log;
  int page = 0, take = 0, microphone = 0, preset = 0;
  bool recording = false, has_take = false, strict = false;
  std::vector<std::string> microphones{"Default microphone"};
  AudioIO audio;
  std::atomic<bool> busy{false};
  std::jthread worker;
  std::mutex mutex;
  std::string status = "Choose recordings or record the prepared script.",
              summary;
  std::vector<std::string> plan;
  std::vector<std::uint8_t> rendered;
  std::unique_ptr<phonomenal_splicer::VoiceBank> bank;
  fs::path loaded_path;
  fs::file_time_type loaded_time{};
  void message(std::string s) {
    std::lock_guard guard(mutex);
    status = std::move(s);
  }
  void task(std::function<void(std::stop_token)> fn) {
    if (busy)
      return;
    if (worker.joinable())
      worker.join();
    busy = true;
    worker = std::jthread([this, fn = std::move(fn)](std::stop_token stop) {
      try {
        fn(stop);
      } catch (const std::exception &e) {
        message(e.what());
      }
      busy = false;
    });
  }
  ~App() {
    if (worker.joinable()) {
      worker.request_stop();
      worker.join();
    }
  }
};
static void build(App &a) {
  const auto source = std::string(a.source), output = std::string(a.output),
             voice = std::string(a.voice), python = std::string(a.python),
             mfa = std::string(a.mfa);
  const bool tf2 = a.preset < 9;
  a.message(
      "Building: decode, recognize words, refine phoneme boundaries, package.");
  a.task([&, source, output, voice, python, mfa, tf2](std::stop_token stop) {
    std::vector<std::string> cmd{
        python,          utf8(a.root / "scripts/builder.py"),
        "build-pack",    source,
        "--output",      output,
        "--voice",       voice,
        "--mfa-command", mfa};
    if (tf2)
      cmd.push_back("--tf2");
    int rc = RunChild(cmd, a.root, a.log, stop);
    if (rc != 0)
      throw std::runtime_error(
          stop.stop_requested()
              ? "Build cancelled; completed stages can be resumed."
              : "Build failed. See the builder log below.");
    auto verified = phonomenal_splicer::VoiceBank::Load(path_utf8(output));
    a.message("Pack built and validated by the C++ reader: " + verified.merc());
  });
}
static void synthesize(App &a) {
  const auto path = path_utf8(a.pack);
  const auto text = std::string(a.prompt);
  const bool strict = a.strict;
  a.message("Selecting speech chunks...");
  a.task([&, path, text, strict](std::stop_token stop) {
    auto stamp = fs::last_write_time(path);
    if (!a.bank || a.loaded_path != path || a.loaded_time != stamp) {
      a.bank = std::make_unique<phonomenal_splicer::VoiceBank>(
          phonomenal_splicer::VoiceBank::Load(path));
      a.loaded_path = path;
      a.loaded_time = stamp;
    }
    phonomenal_splicer::SynthesizeOptions options;
    options.strict = strict;
    options.stop_token = stop;
    auto started = std::chrono::steady_clock::now();
    auto plan = a.bank->PlanText(text, options);
    auto wav = a.bank->SynthesizeWav(plan, options);
    std::vector<std::string> lines;
    for (const auto &u : plan.units) {
      std::ostringstream line;
      line << u.target_text << " | "
           << phonomenal_splicer::UnitKindToString(u.kind) << " | "
           << std::fixed << std::setprecision(3)
           << 1000. * u.start_sample / plan.sample_rate << " - "
           << 1000. * u.end_sample / plan.sample_rate << " ms | " << u.clip_id;
      lines.push_back(line.str());
    }
    for (const auto &warning : plan.warnings)
      lines.push_back("Notice: " + warning);
    auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(
                       std::chrono::steady_clock::now() - started)
                       .count();
    std::lock_guard guard(a.mutex);
    a.rendered = std::move(wav);
    a.plan = std::move(lines);
    a.summary = a.bank->merc() + " | " + std::to_string(plan.sample_rate) +
                " Hz | " + std::to_string(plan.units.size()) +
                " recorded chunks | " + std::to_string(elapsed) + " ms";
    a.status = "Ready. Play to listen, or export the WAV.";
  });
}
int main(int argc, char **argv) {
  App a;
  a.root = find_root(argv[0]);
  a.log = a.root / "data/frontend-builder.log";
  fs::create_directories(a.log.parent_path());
  copy(a.source, utf8(a.root / "source/heavy"));
  copy(a.output, utf8(a.root / "data/packages/heavy.vcpack"));
  copy(a.voice, "heavy");
#ifdef _WIN32
  const auto python = a.root / ".venv-vcpack/Scripts/python.exe";
  copy(a.mfa, "mfa");
#else
  const auto python = a.root / ".venv-vcpack/bin/python";
  copy(a.mfa, fs::exists(a.root / ".tools/aligner")
                  ? utf8(a.root / "scripts/mfa-local")
                  : "mfa");
#endif
  copy(a.python, fs::exists(python) ? utf8(python) : "python");
  copy(a.wav_path, utf8(a.root / "data/spliced/message.wav"));
  copy(a.prompt, "Hello there. I need a little more time.");
  if (fs::exists(a.root / "data/packages"))
    for (const auto &entry : fs::directory_iterator(a.root / "data/packages"))
      if (entry.path().extension() == ".vcpack") {
        copy(a.pack, utf8(entry.path()));
        break;
      }
  if (fs::exists(a.root / "data/packages/heavy.vcpack"))
    copy(a.pack, utf8(a.root / "data/packages/heavy.vcpack"));
  for (int i = 1; i < argc; ++i) {
    if (std::string(argv[i]) == "--player")
      a.page = 1;
    else if (std::string(argv[i]) == "--builder")
      a.page = 0;
  }
  ft::Config cfg;
  cfg.title = "Phonomenal | Voice Builder & TTS";
  cfg.width = 1050;
  cfg.height = 850;
  cfg.web_host = "127.0.0.1";
  cfg.fps_limit = 30;
  if (!ft::create_window(cfg, argc, argv))
    return 1;
  ft::set_style(ft::gruvbox_dark_style());
  while (ft::pump()) {
    ft::begin();
    ft::text("PHONOMENAL");
    ft::text("Your recordings. Your words. Precise speech mixing.");
    const char *tabs[] = {"Voice pack builder", "C++ TTS / player"};
    ft::tabs(tabs, 2, &a.page);
    ft::separator();
    try {
      if (a.page == 0) {
        ft::text("Default target: TF2 mercs. Build Heavy first, then Medic, "
                 "then Soldier.");
        const char *presets[] = {"Heavy",   "Medic",       "Soldier", "Scout",
                                 "Demoman", "Engineer",    "Sniper",  "Spy",
                                 "Pyro",    "My own voice"};
        const char *ids[] = {"heavy",   "medic",    "soldier", "scout",
                             "demoman", "engineer", "sniper",  "spy",
                             "pyro",    "my-voice"};
        if (ft::dropdown("Voice preset", presets, 10, &a.preset) && !a.busy &&
            !a.recording && !a.has_take) {
          copy(a.voice, ids[a.preset]);
          copy(a.source,
               utf8(a.root / (a.preset == 9 ? "recordings" : "source") /
                    ids[a.preset]));
          copy(a.output, utf8(a.root / "data/packages" /
                              (std::string(ids[a.preset]) + ".vcpack")));
        }
        ft::text(
            "Use My own voice for the prepared microphone recording script.");
        ft::input("Voice name", a.voice, sizeof(a.voice));
        ft::input("Recordings folder", a.source, sizeof(a.source));
        ft::input("Output .vcpack", a.output, sizeof(a.output));
        ft::separator();
        ft::text("Prepared reading script: 124 takes, 1,513 words, all 39 "
                 "English phonemes.");
        ft::text("Read naturally. Leave a short pause before and after each "
                 "take. Redo mistakes.");
        std::string title = "Take " + std::to_string(a.take + 1) + " / " +
                            std::to_string(kReadingScript.size());
        ft::text(title.c_str());
        ft::text_wrapped(
            kReadingScript[static_cast<std::size_t>(a.take)].c_str());
        ft::row(3, [&] {
          if (ft::button("Previous take") && !a.recording && !a.has_take)
            a.take = std::max(0, a.take - 1);
          if (ft::button("Next take") && !a.recording && !a.has_take)
            a.take = std::min(static_cast<int>(kReadingScript.size()) - 1,
                              a.take + 1);
          if (ft::button("Refresh microphones") && !a.recording)
            a.microphones = a.audio.capture_devices();
        });
        std::vector<const char *> devices;
        for (const auto &d : a.microphones)
          devices.push_back(d.c_str());
        ft::dropdown("Microphone", devices.data(),
                     static_cast<int>(devices.size()), &a.microphone);
        ft::row(3, [&] {
          if (ft::button(a.recording ? "Stop recording" : "Record this take") &&
              !a.busy) {
            if (a.recording) {
              a.audio.stop_record();
              a.recording = false;
              a.has_take = true;
              a.message("Take stopped. Save it or discard and record again.");
            } else {
              a.audio.record(a.microphone);
              a.recording = true;
              a.has_take = false;
              a.message("Recording microphone...");
            }
          }
          if (ft::button("Save take + transcript") && a.has_take &&
              !a.recording) {
            std::ostringstream name;
            name << "take_" << std::setw(3) << std::setfill('0') << a.take + 1;
            auto path = path_utf8(a.source) / (name.str() + ".wav");
            if (fs::exists(path))
              throw std::runtime_error(
                  "This take already exists; choose another recordings folder "
                  "or remove the old take deliberately.");
            a.audio.save_recording(path);
            std::ofstream transcript(path.parent_path() /
                                     (name.str() + ".txt"));
            transcript << kReadingScript[static_cast<std::size_t>(a.take)]
                       << '\n';
            if (!transcript)
              throw std::runtime_error("Could not save take transcript");
            a.has_take = false;
            a.take = std::min(static_cast<int>(kReadingScript.size()) - 1,
                              a.take + 1);
            a.message("Saved recording with its exact transcript.");
          }
          if (ft::button("Discard take") && !a.recording) {
            a.has_take = false;
            a.message("Take discarded. Ready to record again.");
          }
        });
        if (a.recording) {
          ft::progress_bar(a.audio.level());
          std::string meter =
              std::to_string(static_cast<int>(a.audio.seconds())) +
              " s recorded (maximum 180 s per take)";
          ft::text(meter.c_str());
          if (a.audio.seconds() >= 180) {
            a.audio.stop_record();
            a.recording = false;
            a.has_take = true;
          }
        }
        ft::separator();
        ft::text("Builder setup");
        ft::input("Python executable", a.python, sizeof(a.python));
        ft::input("MFA command", a.mfa, sizeof(a.mfa));
        ft::text_wrapped(
            "The builder uses real word and phoneme alignment with a 1 ms "
            "refinement grid. Measured accuracy is reported separately; "
            "decimal precision alone does not prove a good cut.");
        ft::row(2, [&] {
          if (ft::button(a.busy ? "Build running..."
                                : "Build / resume voice pack") &&
              !a.busy && !a.recording)
            build(a);
          if (ft::button("Use built pack in player") && !a.busy) {
            copy(a.pack, a.output);
            a.page = 1;
          }
        });
        if (fs::exists(a.log)) {
          ft::separator();
          ft::text("Builder log");
          auto log = read_tail(a.log);
          ft::text_wrapped(log.c_str());
        }
      } else {
        ft::text("Load a .vcpack and type any message. The native engine "
                 "reuses the longest suitable recordings.");
        ft::input("Voice pack", a.pack, sizeof(a.pack));
        if (ft::button("Browse voice pack") && !a.busy) {
          const ft::FileFilter filters[] = {{"Voice packs", "*.vcpack"},
                                            {"Legacy banks", "*.phbank"}};
          auto path = ft::open_file_dialog("Open voice pack", filters, 2);
          if (!path.empty())
            copy(a.pack, path);
        }
        ft::input("Message", a.prompt, sizeof(a.prompt));
        ft::checkbox("Strict sound coverage (reject approximations)",
                     &a.strict);
        ft::row(3, [&] {
          if (ft::button(a.busy ? "Synthesizing..." : "Generate speech") &&
              !a.busy)
            synthesize(a);
          if (ft::button("Play") && !a.busy) {
            std::lock_guard guard(a.mutex);
            if (a.rendered.empty())
              throw std::runtime_error("Generate speech first");
            a.audio.play(a.rendered);
          }
          if (ft::button("Stop playback"))
            a.audio.stop_playback();
        });
        ft::input("Export WAV", a.wav_path, sizeof(a.wav_path));
        if (ft::button("Save generated WAV") && !a.busy) {
          std::lock_guard guard(a.mutex);
          if (a.rendered.empty())
            throw std::runtime_error("Generate speech first");
          auto path = path_utf8(a.wav_path);
          if (!path.parent_path().empty())
            fs::create_directories(path.parent_path());
          std::ofstream file(path, std::ios::binary);
          file.write(reinterpret_cast<const char *>(a.rendered.data()),
                     static_cast<std::streamsize>(a.rendered.size()));
          if (!file)
            throw std::runtime_error("Could not export WAV");
          a.status = "WAV exported.";
        }
        std::lock_guard guard(a.mutex);
        ft::separator();
        ft::text_wrapped(a.summary.c_str());
        ft::text("Selected chunks (millisecond positions in pack audio)");
        for (const auto &line : a.plan)
          ft::text_wrapped(line.c_str());
      }
      if (a.busy && ft::button("Cancel current job"))
        a.worker.request_stop();
    } catch (const std::exception &e) {
      a.message(e.what());
    }
    {
      std::lock_guard guard(a.mutex);
      ft::separator();
      ft::text_wrapped(a.status.c_str());
    }
    if (a.busy || a.recording)
      ft::request_redraw();
    ft::end();
  }
  if (a.worker.joinable()) {
    a.worker.request_stop();
    a.worker.join();
  }
  a.audio.stop_record();
  a.audio.stop_playback();
  ft::shutdown();
  return 0;
}
