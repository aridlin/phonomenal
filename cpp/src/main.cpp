#include "phonomenal_splicer/splicer.h"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <vector>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#endif
static std::string quote(const std::string &s) {
  std::ostringstream o;
  o << '"';
  for (unsigned char c : s) {
    switch (c) {
    case '"':
      o << "\\\"";
      break;
    case '\\':
      o << "\\\\";
      break;
    case '\n':
      o << "\\n";
      break;
    case '\r':
      o << "\\r";
      break;
    case '\t':
      o << "\\t";
      break;
    default:
      if (c < 32)
        o << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c)
          << std::dec;
      else
        o << c;
    }
  }
  o << '"';
  return o.str();
}
static void print_plan(const phonomenal_splicer::PlanResult &p,
                       std::ostream &o) {
  o << "{\"voice\":" << quote(p.merc)
    << ",\"normalized_text\":" << quote(p.normalized_text)
    << ",\"sample_rate\":" << p.sample_rate << ",\"score\":" << p.score
    << ",\"warnings\":[";
  for (std::size_t i = 0; i < p.warnings.size(); ++i) {
    if (i)
      o << ',';
    o << quote(p.warnings[i]);
  }
  o << "],\"units\":[";
  for (std::size_t i = 0; i < p.units.size(); ++i) {
    const auto &u = p.units[i];
    if (i)
      o << ',';
    o << "{\"kind\":" << quote(phonomenal_splicer::UnitKindToString(u.kind))
      << ",\"target_text\":" << quote(u.target_text)
      << ",\"text\":" << quote(u.text) << ",\"clip_id\":" << quote(u.clip_id)
      << ",\"start_sample\":" << u.start_sample
      << ",\"end_sample\":" << u.end_sample
      << ",\"pause_before_ms\":" << u.pause_before_ms
      << ",\"approximate\":" << (u.approximated ? "true" : "false");
    if(u.starts_at_phone_center || u.ends_at_phone_center)
      o << ",\"starts_at_phone_center\":" << (u.starts_at_phone_center?"true":"false")
        << ",\"ends_at_phone_center\":" << (u.ends_at_phone_center?"true":"false");
    if(u.center_run_phone_count>2) o << ",\"center_run_phone_count\":" << u.center_run_phone_count;
    o << "}";
  }
  o << "]}\n";
}
static std::filesystem::path utf8_path(const std::string &value) {
  return std::filesystem::path(std::u8string(
      reinterpret_cast<const char8_t *>(value.data()), value.size()));
}

static int run_cli(int argc, char **argv) {
  try {
    std::filesystem::path bank_path, output_path, audit_path;
    std::string text, phones;
    bool stdout_wav = false, plan_only = false, inspect = false,
         stdin_text = false;
    phonomenal_splicer::SynthesizeOptions options;
    for (int i = 1; i < argc; ++i) {
      std::string arg = argv[i];
      auto value = [&] {
        if (++i >= argc)
          throw std::runtime_error("Missing value for " + arg);
        return std::string(argv[i]);
      };
      if (arg == "--bank")
        bank_path = utf8_path(value());
      else if (arg == "--text")
        text = value();
      else if (arg == "--phones")
        phones = value();
      else if (arg == "--output")
        output_path = utf8_path(value());
      else if (arg == "--audit")
        audit_path = utf8_path(value());
      else if (arg == "--no-auto-word-gaps")
        options.adaptive_word_gaps = false;
      else if (arg == "--normalize-duration")
        options.normalize_duration = true;
      else if (arg == "--acoustic-phone-scores")
        options.acoustic_phone_scores = true;
      else if (arg == "--match-pitch")
        options.match_pitch = true;
      else if (arg == "--center-phone-joins") {
        options.center_phone_joins = true;
        options.center_max_phone_run = 2;
        options.preserve_phone_timing = true;
      }
      else if (arg == "--center-run-phones") {
        const auto input=value();std::size_t consumed=0;
        const auto count=std::stoll(input,&consumed);
        if(consumed!=input.size() || count<2 || count>12) throw std::runtime_error("Center phone run must be between 2 and 12");
        options.center_max_phone_run=static_cast<std::size_t>(count);
        options.center_phone_joins=true;
        options.preserve_phone_timing=true;
      }
      else if (arg == "--preserve-phone-timing")
        options.preserve_phone_timing = true;
      else if (arg == "--legacy-overlap" || arg == "--boundary-phone-joins") {
        options.center_phone_joins = false;
        options.preserve_phone_timing = false;
      }
      else if (arg == "--word-gap-ms")
        options.word_gap_ms = std::clamp<std::int64_t>(std::stoll(value()),0,500);
      else if (arg == "--pitch-band") {
        auto band=value(); auto separator=band.find(':');
        if(separator==std::string::npos) throw std::runtime_error("Pitch band must be LOWER:UPPER in Hz");
        options.pitch_floor_hz=std::stod(band.substr(0,separator));
        options.pitch_ceiling_hz=std::stod(band.substr(separator+1));
      }
      else if (arg == "--stdout-wav")
        stdout_wav = true;
      else if (arg == "--plan")
        plan_only = true;
      else if (arg == "--inspect")
        inspect = true;
      else if (arg == "--stdin")
        stdin_text = true;
      else if (arg == "--strict")
        options.strict = true;
      else if (arg == "--beam")
        options.beam_width = std::stoul(value());
      else if (arg == "--help" || arg == "-h") {
        std::cout
            << "phonomenal_splicer_cli --bank voice.vcpack (--text TEXT | "
               "--stdin | --phones PHONES) [--output speech.wav] "
               "[--stdout-wav] [--plan] [--strict] [--audit report.json] [--match-pitch] [--acoustic-phone-scores] [--center-phone-joins] [--center-run-phones 2..12] [--boundary-phone-joins] [--preserve-phone-timing] [--legacy-overlap] [--pitch-band 100:180]\nphonomenal_splicer_cli "
               "--bank voice.vcpack --inspect\n";
        return 0;
      } else
        throw std::runtime_error("Unknown argument: " + arg);
    }
    if (bank_path.empty())
      throw std::runtime_error("Expected --bank");
    if (stdin_text) {
      if (!text.empty() || !phones.empty())
        throw std::runtime_error("--stdin cannot accompany --text/--phones");
      text.assign(std::istreambuf_iterator<char>(std::cin), {});
    }
    auto bank = phonomenal_splicer::VoiceBank::Load(bank_path);
    if (inspect) {
      std::cout << (bank.quality_report().empty() ? "{}"
                                                  : bank.quality_report())
                << '\n';
      return 0;
    }
    if (text.empty() == phones.empty())
      throw std::runtime_error(
          "Expected exactly one of --text, --stdin or --phones");
    if (!stdout_wav && !plan_only && output_path.empty())
      throw std::runtime_error("Expected --output, --stdout-wav or --plan");
    std::vector<std::string> phone_list;
    std::istringstream in(phones);
    for (std::string p; in >> p;)
      phone_list.push_back(p);
    auto plan = !text.empty() ? bank.PlanText(text, options)
                              : bank.PlanPhonemes(phone_list, options);
    if (plan_only)
      print_plan(plan, stdout_wav ? std::cerr : std::cout);
    else
      for (const auto &warning : plan.warnings)
        std::cerr << warning << '\n';
    if (stdout_wav || !output_path.empty()) {
      phonomenal_splicer::BoundaryReport audit;
      auto wav = bank.SynthesizeWav(plan, options, &audit);
      if (!audit_path.empty()) {
        if(!audit_path.parent_path().empty()) std::filesystem::create_directories(audit_path.parent_path());
        std::ofstream report(audit_path);
        report << phonomenal_splicer::BoundaryReportJson(audit);
        if(!report) throw std::runtime_error("Could not write boundary audit");
      }
      if (stdout_wav) {
#ifdef _WIN32
        _setmode(_fileno(stdout), _O_BINARY);
#endif
        std::cout.write(reinterpret_cast<const char *>(wav.data()),
                        static_cast<std::streamsize>(wav.size()));
        if (!std::cout)
          throw std::runtime_error("Audio stdout failed");
      }
      if (!output_path.empty()) {
        if (!output_path.parent_path().empty())
          std::filesystem::create_directories(output_path.parent_path());
        std::ofstream out(output_path, std::ios::binary);
        out.write(reinterpret_cast<const char *>(wav.data()),
                  static_cast<std::streamsize>(wav.size()));
        if (!out)
          throw std::runtime_error("Could not write WAV");
      }
    }
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "phonomenal: " << e.what() << '\n';
    return 1;
  }
}

#ifdef _WIN32
int wmain(int argc, wchar_t **wide_argv) {
  std::vector<std::string> values;
  values.reserve(argc);
  for(int i=0;i<argc;++i) {
    const auto count=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide_argv[i],-1,nullptr,0,nullptr,nullptr);
    if(!count) {std::cerr << "Invalid Unicode command-line argument\n";return 1;}
    std::string text(static_cast<std::size_t>(count),'\0');
    WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide_argv[i],-1,text.data(),count,nullptr,nullptr);
    text.pop_back();values.push_back(std::move(text));
  }
  std::vector<char *> argv;
  argv.reserve(static_cast<std::size_t>(argc)+1);
  for(auto &value:values) argv.push_back(value.data());
  argv.push_back(nullptr);
  return run_cli(argc,argv.data());
}
#else
int main(int argc, char **argv) { return run_cli(argc,argv); }
#endif
