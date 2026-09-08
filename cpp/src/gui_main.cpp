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
static fs::path path_utf8(const std::string &s) {
  return fs::path(
      std::u8string(reinterpret_cast<const char8_t *>(s.data()), s.size()));
}
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
  int page = 0, take = 0, microphone = 0, preset = 0, selected_pack = 0;
  std::vector<fs::path> pack_paths;
  std::vector<std::string> pack_labels;
  bool recording = false, has_take = false, strict = false, auto_check = true, pitch_band = false;
  float pitch_floor = 100.f, pitch_ceiling = 180.f;
  std::vector<std::string> microphones{"Default microphone"};
  AudioIO audio;
  std::atomic<bool> busy{false};
  std::jthread worker;
  std::mutex mutex;
  std::string status = "Choose recordings or record the prepared script.",
              summary;
  std::vector<std::string> plan;
  std::vector<std::uint8_t> rendered;
  std::string rendered_prompt, stt_result, public_wave, public_pack, audit_result, public_audit;
  std::string web_files_url = "/phonomenal/files/";
  fs::path editor_project;
  std::vector<std::string> editor_files, editor_labels;
  std::vector<char> editor_text = std::vector<char>(16 * 1024 * 1024, 0);
  int editor_selected = 0, editor_loaded = 0;
  bool editor_dirty = false;
  char editor_start[32]{}, editor_end[32]{};
  std::string editor_wave, editor_svg, editor_download;
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
static void refresh_packs(App &a, const fs::path &imported = {}) {
  std::vector<fs::path> paths;
  auto add = [&](const fs::path &path) {
    std::error_code ec;
    auto absolute = fs::weakly_canonical(path, ec);
    if (!ec && fs::is_regular_file(absolute, ec) &&
        (absolute.extension() == ".vcpack" ||
         absolute.extension() == ".phbank") &&
        std::find(paths.begin(), paths.end(), absolute) == paths.end())
      paths.push_back(absolute);
  };
  for (const auto &folder : {a.root / "data/packages", a.root / "packs"}) {
    std::error_code ec;
    if (fs::is_directory(folder, ec))
      for (const auto &entry : fs::directory_iterator(folder))
        add(entry.path());
  }
  std::ifstream history(a.root / "data/imported-vcpacks.txt");
  std::string path;
  while (history >> std::quoted(path))
    add(path_utf8(path));
  if (a.pack[0])
    add(path_utf8(a.pack));
  if (!imported.empty())
    add(imported);
  const std::vector<std::string> priority{"heavy",  "medic",   "soldier",
                                          "scout",  "demoman", "engineer",
                                          "sniper", "spy",     "pyro"};
  auto rank = [&](const fs::path &p) {
    auto found = std::find(priority.begin(), priority.end(), utf8(p.stem()));
    return std::distance(priority.begin(), found);
  };
  std::stable_sort(paths.begin(), paths.end(),
                   [&](const auto &l, const auto &r) {
                     if (rank(l) != rank(r))
                       return rank(l) < rank(r);
                     return utf8(l) < utf8(r);
                   });
  std::erase_if(paths, [&](const fs::path &p) {
    if (p.extension() != ".phbank")
      return false;
    auto modern = p;
    modern.replace_extension(".vcpack");
    return fs::is_regular_file(modern);
  });
  a.pack_paths = paths;
  a.pack_labels.clear();
  a.selected_pack = 0;
  for (std::size_t i = 0; i < paths.size(); ++i) {
    a.pack_labels.push_back(utf8(paths[i].filename()) + "  |  " +
                            utf8(paths[i].parent_path().filename()));
    if (paths[i] == path_utf8(a.pack))
      a.selected_pack = static_cast<int>(i);
  }
  std::ofstream saved(a.root / "data/imported-vcpacks.txt.tmp");
  for (const auto &p : paths)
    saved << std::quoted(utf8(p)) << '\n';
  saved.close();
  if (!saved)
    throw std::runtime_error("Could not save imported pack list");
  std::error_code ec;
#ifdef _WIN32
  fs::remove(a.root / "data/imported-vcpacks.txt", ec);
#endif
  fs::rename(a.root / "data/imported-vcpacks.txt.tmp",
             a.root / "data/imported-vcpacks.txt");
}
static void choose_pack(App &a, const fs::path &path) {
  if (a.busy)
    return;
  a.audio.stop_playback();
  copy(a.pack, utf8(path));
  a.rendered.clear();
  a.plan.clear();
  a.summary.clear();
  a.stt_result.clear();
  a.audit_result.clear();
  a.public_audit.clear();
  a.public_wave.clear();
  a.public_pack.clear();
  a.message("Voice selected. Generate a message to listen.");
  refresh_packs(a, path);
}
#include "web_ui.inc"
#include "editor_ui.inc"
static void check_audio(App &a, const std::vector<std::uint8_t> &wav, const std::string &expected, const std::string &python, std::stop_token stop) {
    auto folder = a.root / "data/speech-check";
    fs::create_directories(folder);
    auto audio = folder / "generated.wav", log = folder / "stt.log";
    std::ofstream file(audio, std::ios::binary);
    file.write(reinterpret_cast<const char *>(wav.data()),
               static_cast<std::streamsize>(wav.size()));
    file.close();
    if (!file)
      throw std::runtime_error("Could not save speech-check audio");
    int rc = RunChild({python, utf8(a.root / "scripts/builder.py"),
                       "verify-speech", utf8(audio), "--text", expected,
                       "--json-output", utf8(folder / "report.json")},
                      a.root, log, stop);
    if (stop.stop_requested()) {
      a.message("Speech check cancelled.");
      return;
    }
    if (rc)
      throw std::runtime_error(
          "Speech check failed. Run the builder setup first. " +
          read_tail(log));
    {
      std::lock_guard guard(a.mutex);
      a.stt_result = read_tail(log);
    }
    a.message("Speech check complete. Results appear below the STT button.");
}
static void build(App &a) {
  const auto source = std::string(a.source), output = std::string(a.output),
             voice = std::string(a.voice), python = std::string(a.python),
             mfa = std::string(a.mfa);
  const bool tf2 = a.preset < 9;
  const bool browser = web_mode();
  a.message(
      "Building: decode, recognize words, refine phoneme boundaries, package.");
  a.task([&, source, output, voice, python, mfa, tf2,
          browser](std::stop_token stop) {
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
    if (browser) {
      fs::create_directories(a.root / "data/public");
      auto name = unique_web_name(".vcpack");
      fs::copy_file(path_utf8(output), a.root / "data/public" / name);
      std::lock_guard guard(a.mutex);
      a.public_pack = a.web_files_url + name;
    }
    a.message("Pack built and validated by the C++ reader: " + verified.merc());
  });
}
static void synthesize(App &a) {
  const auto path = path_utf8(a.pack);
  const auto text = std::string(a.prompt);
  const bool strict = a.strict;
  const bool browser = web_mode();
  const bool auto_check = a.auto_check, pitch_band = a.pitch_band;
  const double pitch_floor = a.pitch_floor, pitch_ceiling = a.pitch_ceiling;
  const std::string python = a.python;
  a.message("Selecting speech chunks...");
  a.task([&, path, text, strict, browser, auto_check, pitch_band,
          pitch_floor, pitch_ceiling, python](std::stop_token stop) {
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
    if (pitch_band) { options.pitch_floor_hz=pitch_floor; options.pitch_ceiling_hz=pitch_ceiling; }
    auto started = std::chrono::steady_clock::now();
    auto plan = a.bank->PlanText(text, options);
    phonomenal_splicer::BoundaryReport audit;
    auto wav = a.bank->SynthesizeWav(plan, options, &audit);
    const auto audit_json=phonomenal_splicer::BoundaryReportJson(audit);
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
    std::string public_wave;
    if (browser) {
      fs::create_directories(a.root / "data/public");
      auto name = unique_web_name(".wav");
      std::ofstream output(a.root / "data/public" / name, std::ios::binary);
      output.write(reinterpret_cast<const char *>(wav.data()), wav.size());
      if (!output)
        throw std::runtime_error("Could not publish generated audio");
      public_wave = a.web_files_url + name;
    }
    auto audit_file=a.root/"data/spliced/boundaries.json";
    fs::create_directories(audit_file.parent_path());
    { std::ofstream file(audit_file); file << audit_json; if(!file)throw std::runtime_error("Could not write boundary report"); }
    std::string public_audit;
    if(browser) {
      auto name=unique_web_name(".json");fs::copy_file(audit_file,a.root/"data/public"/name);
      public_audit=a.web_files_url+name;
    }
    {
    std::lock_guard guard(a.mutex);
    a.public_audit=public_audit;
    a.audit_result="Boundary checks: " + std::to_string(audit.boundaries.size()) + " edges checked, " + std::to_string(audit.flagged) + " flagged. Pitch-adjusted chunks: " + std::to_string(audit.pitch_adjustments.size()) + ". Timing correctness still requires listening/review.";
    a.public_wave = public_wave;
    a.rendered = wav;
    a.rendered_prompt = text;
    a.stt_result.clear();
    a.plan = std::move(lines);
    a.summary = a.bank->merc() + " | " + std::to_string(plan.sample_rate) +
                " Hz | " + std::to_string(plan.units.size()) +
                " recorded chunks | " + std::to_string(elapsed) + " ms";
    a.status = "Audio ready. Every selected boundary has been checked.";
    }
    if(auto_check) {
      a.message("Audio ready. Automatically checking the rendered words...");
      try { check_audio(a,wav,text,python,stop); }
      catch(const std::exception &e) { a.message(std::string("Audio ready; automatic STT check failed: ")+e.what()); }
    }
  });
}
static void verify_rendered(App &a) {
  if (a.rendered.empty())
    throw std::runtime_error("Generate speech first");
  const auto wav = a.rendered;
  const auto expected = a.rendered_prompt;
  const auto python = std::string(a.python);
  a.message(
      "Checking the generated audio with unprompted speech recognition...");
  a.task([&, wav, expected, python](std::stop_token stop) {
    check_audio(a, wav, expected, python, stop);
  });
}
int main(int argc, char **argv) {
  App a;
  int web_port = 8766;
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
    else if (std::string(argv[i]) == "--pack" && i + 1 < argc)
      copy(a.pack, utf8(fs::absolute(path_utf8(argv[++i]))));
    else if (std::string(argv[i]) == "--text" && i + 1 < argc)
      copy(a.prompt, argv[++i]);
    else if (std::string(argv[i]) == "--web-port" && i + 1 < argc)
      web_port = std::stoi(argv[++i]);
  }
  refresh_packs(a);
  ft::Config cfg;
  cfg.title = "Phonomenal | Voice Builder & TTS";
  cfg.width = 1050;
  cfg.height = 850;
  cfg.web_host = "127.0.0.1";
  cfg.web_port = web_port;
  cfg.web_max_request_bytes = 320 * 1024 * 1024;
  cfg.web_read_timeout_ms = 30000;
  cfg.web_client_poll_ms = 0;
  cfg.web_extra_head_html = web_head;
  cfg.web_dark_mode = true;
  cfg.fps_limit = 30;
  if (!ft::create_window(cfg, argc, argv))
    return 1;
  ft::set_style(ft::gruvbox_dark_style());
  while (ft::pump()) {
    ft::begin();
    std::string render_revision;
    if (web_mode()) {
      if (!a.busy) refresh_packs(a);
      render_revision = web_revision(a);
      const char *known = ft::param("voice_revision");
      if (known && render_revision == known) {
        ft::set_status(204, "No Content");
        ft::end();
        continue;
      }
    }
    ft::text("PHONOMENAL");
    ft::text("Your recordings. Your words. Precise speech mixing.");
    const char *tabs[] = {"Voice pack builder", "C++ TTS / player", "Voice pack editor"};
    ft::tabs(tabs, 3, &a.page);
    ft::separator();
    try {
      if (web_mode()) {
        try {
          web_upload(a);
        } catch (const std::exception &e) {
          ft::set_status(a.busy ? 409 : 400, "Upload rejected");
          a.message(e.what());
        }
        ft::text("Shared Phonomenal workspace. Audio plays and records in your "
                 "browser.");
        web_upload_control();
        ft::separator();
      }
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
        if (!web_mode()) {
          ft::input("Recordings folder", a.source, sizeof(a.source));
          ft::input("Output .vcpack", a.output, sizeof(a.output));
        }
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
        if (web_mode()) {
          if (ft::button("New recording session") && !a.busy) {
            a.preset = 9;
            a.take = 0;
            copy(a.voice, "my-voice");
            copy(a.source,
                 utf8(a.root / "recordings" / unique_web_name("-voice")));
            copy(a.output,
                 utf8(a.root / "data/packages" / unique_web_name(".vcpack")));
            a.message("New voice session. Upload or record one speaker here.");
          }
          ft::row(2, [&] {
            if (ft::button("Previous take") && !a.busy)
              a.take = std::max(0, a.take - 1);
            if (ft::button("Next take") && !a.busy)
              a.take = std::min(static_cast<int>(kReadingScript.size()) - 1,
                                a.take + 1);
          });
          web_recorder(a);
        } else {
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
            if (ft::button(a.recording ? "Stop recording"
                                       : "Record this take") &&
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
              name << "take_" << std::setw(3) << std::setfill('0')
                   << a.take + 1;
              auto path = path_utf8(a.source) / (name.str() + ".wav");
              if (fs::exists(path))
                throw std::runtime_error(
                    "This take already exists; choose another recordings "
                    "folder "
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
        }
        ft::separator();
        if (!web_mode()) {
          ft::text("Builder setup");
          ft::input("Python executable", a.python, sizeof(a.python));
          ft::input("MFA command", a.mfa, sizeof(a.mfa));
          ft::text_wrapped(
              "The builder uses real word and phoneme alignment with a 1 ms "
              "refinement grid. Measured accuracy is reported separately; "
              "decimal precision alone does not prove a good cut.");
        }
        ft::row(2, [&] {
          if (ft::button(a.busy ? "Build running..."
                                : "Build / resume voice pack") &&
              !a.busy && !a.recording)
            build(a);
          if (ft::button("Use built pack in player") && !a.busy) {
            choose_pack(a, path_utf8(a.output));
            a.page = 1;
          }
        });
        web_region_begin("builder-results");
        if (web_mode()) {
          std::lock_guard guard(a.mutex);
          if (!a.public_pack.empty())
            ft::html(("<p><a download href=\"" + web_escape(a.public_pack) +
                      "\">Download built voice pack</a></p>")
                         .c_str());
        }
        if (fs::exists(a.log)) {
          ft::separator();
          ft::text("Builder log");
          auto log = read_tail(a.log);
          ft::log_view("Alignment progress", log.c_str(), 8);
        }
        web_region_end();
      } else if (a.page == 2) {
        editor_ui(a);
      } else {
        ft::text("Load a .vcpack and type any message. The native engine "
                 "reuses the longest suitable recordings.");
        web_region_begin("pack-list");
        if (!a.pack_labels.empty()) {
          std::vector<const char *> labels;
          for (const auto &label : a.pack_labels)
            labels.push_back(label.c_str());
          int selected = a.selected_pack;
          if (ft::dropdown("Imported voice packs", labels.data(),
                           static_cast<int>(labels.size()), &selected) &&
              !a.busy)
            choose_pack(a, a.pack_paths.at(static_cast<std::size_t>(selected)));
        } else
          ft::text("No voice packs yet. Browse to import one.");
        if (ft::button("Refresh pack list") && !a.busy)
          refresh_packs(a);
        web_region_end();
        if (!web_mode()) {
          ft::input("Voice pack", a.pack, sizeof(a.pack));
          if (ft::button("Browse voice pack") && !a.busy) {
            const ft::FileFilter filters[] = {{"Voice packs", "*.vcpack"},
                                              {"Legacy banks", "*.phbank"}};
            auto path = ft::open_file_dialog("Open voice pack", filters, 2);
            if (!path.empty())
              choose_pack(a, path_utf8(path));
          }
        }
        ft::input("Message", a.prompt, sizeof(a.prompt));
        ft::checkbox(
            "Strict: reject missing sounds and suspect phone durations",
            &a.strict);
        ft::checkbox("Automatically check generated words with STT", &a.auto_check);
        ft::checkbox("Correct voiced pitch into a band (both low and high)", &a.pitch_band);
        if(a.pitch_band) {
          ft::slider_float("Lowest pitch (Hz)", &a.pitch_floor, 50.f, 400.f);
          ft::slider_float("Highest pitch (Hz)", &a.pitch_ceiling, a.pitch_floor, 600.f);
          a.pitch_ceiling=std::max(a.pitch_ceiling,a.pitch_floor);
          ft::text_wrapped("Adjusts each voiced chunk toward the band while preserving duration. Large shifts can change timbre.");
        }
        ft::text_wrapped(
            "Strict mode cannot repair incorrect source alignments. Rebuild "
            "old packs if words sound cut off.");
        web_region_begin("player-actions");
        ft::row(3, [&] {
          if (ft::button(a.busy ? "Working..." : "Generate speech") &&
              !a.busy)
            synthesize(a);
          if (!web_mode() && ft::button("Play")) {
            std::lock_guard guard(a.mutex);
            if (a.rendered.empty())
              throw std::runtime_error("Generate speech first");
            a.audio.play(a.rendered);
          }
          if (!web_mode() && ft::button("Stop playback"))
            a.audio.stop_playback();
        });
        if (ft::button("Check words with STT") && !a.busy)
          verify_rendered(a);
        ft::text_wrapped("Requires builder setup. Matching words do not "
                         "guarantee natural sound.");
        web_region_end();
        web_region_begin("speech-check");
        {
          std::lock_guard guard(a.mutex);
          if (!a.audit_result.empty()) ft::text_wrapped(a.audit_result.c_str());
          if (web_mode() && !a.public_audit.empty()) ft::html(("<p><a download href=\""+web_escape(a.public_audit)+"\">Download every-boundary report</a></p>").c_str());
          if (!a.stt_result.empty())
            ft::text_wrapped(a.stt_result.c_str());
        }
        web_region_end();
        web_region_begin("player-audio");
        if (web_mode()) {
          std::lock_guard guard(a.mutex);
          if (!a.public_wave.empty())
            ft::html(("<audio controls preload=\"metadata\" src=\"" +
                      web_escape(a.public_wave) +
                      "\"></audio><p><a download href=\"" +
                      web_escape(a.public_wave) +
                      "\">Download generated WAV</a></p>")
                         .c_str());
        } else {
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
        }
        web_region_end();
        web_region_begin("player-plan");
        std::lock_guard guard(a.mutex);
        ft::separator();
        ft::text_wrapped(a.summary.c_str());
        ft::text("Selected chunks (millisecond positions in pack audio)");
        for (const auto &line : a.plan)
          ft::text_wrapped(line.c_str());
        web_region_end();
      }
      web_region_begin("job-actions");
      if (web_mode() && a.busy)
        ft::text("Working. Progress and results update automatically when they change.");
      if (a.busy && ft::button("Cancel current job"))
        a.worker.request_stop();
      web_region_end();
    } catch (const std::exception &e) {
      a.message(e.what());
    }
    web_region_begin("status");
    {
      std::lock_guard guard(a.mutex);
      ft::separator();
      ft::text_wrapped(a.status.c_str());
    }
    web_region_end();
    if (web_mode()) ft::html(("<span hidden id=\"voice-revision\" data-revision=\"" + render_revision + "\" data-page=\"" + std::to_string(a.page) + "\"></span>").c_str());
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
