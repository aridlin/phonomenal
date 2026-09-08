#include "phonomenal_splicer/splicer.h"

#include <algorithm>
#include <bit>
#include <memory>
#include <mutex>
#include <sstream>
#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#else
#include <dlfcn.h>
#endif
#include <array>
#include <cassert>
#include <cmath>
#include <cctype>
#include <cstdint>
#include <fstream>
#include <functional>
#include <limits>
#include <optional>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace phonomenal_splicer {
namespace {

constexpr char kPackageMagic[] = "PHONOMENAL_BANK";
constexpr int kPackageVersion = 2;
constexpr char kKeySeparator = '\x1f';
constexpr int kIndexChunkWords = 8;
constexpr int kIndexPhoneNgram = 12;

struct Word {
    std::string text;
    std::int64_t start_sample{};
    std::int64_t end_sample{};
    std::optional<double> confidence;
};

struct Phoneme {
    std::string label;
    std::string normalized_label;
    std::int64_t word_index{};
    std::int64_t start_sample{};
    std::int64_t end_sample{};
    std::optional<double> confidence;
};

struct Record {
    std::string clip_id;
    std::vector<Word> words;
    std::vector<Phoneme> phonemes;
};

struct ChunkOccurrence {
    std::string text;
    std::vector<std::string> tokens;
    std::string clip_id;
    std::int64_t start_sample{};
    std::int64_t end_sample{};
    std::optional<double> confidence;
};

struct PhoneOccurrence {
    std::vector<std::string> labels;
    std::string clip_id;
    std::int64_t start_sample{};
    std::int64_t end_sample{};
    std::optional<double> confidence;
    std::string source_word;
};

struct PronunciationStats {
    std::vector<std::string> labels;
    int count = 0;
    double confidence_sum = 0.0;
};

struct Candidate {
    double cost = std::numeric_limits<double>::infinity();
    std::vector<PlannedUnit> units;
};

struct WaveData {
    std::int64_t sample_rate{};
    std::vector<std::int16_t> samples;
};

struct AcousticProfile {
    std::optional<double> pitch_hz;
    double rms = 0.0;
};

std::string UnescapeField(std::string_view input) {
    std::string output;
    output.reserve(input.size());
    bool escaping = false;
    for (char ch : input) {
        if (!escaping) {
            if (ch == '\\') {
                escaping = true;
                continue;
            }
            output.push_back(ch);
            continue;
        }

        switch (ch) {
            case 't':
                output.push_back('\t');
                break;
            case 'n':
                output.push_back('\n');
                break;
            case 'r':
                output.push_back('\r');
                break;
            case '\\':
                output.push_back('\\');
                break;
            default:
                output.push_back(ch);
                break;
        }
        escaping = false;
    }
    if (escaping) {
        output.push_back('\\');
    }
    return output;
}

std::vector<std::string> SplitEscapedTabs(std::string_view line) {
    std::vector<std::string> fields;
    std::string current;
    bool escaping = false;
    for (char ch : line) {
        if (!escaping && ch == '\t') {
            fields.push_back(UnescapeField(current));
            current.clear();
            continue;
        }
        if (!escaping && ch == '\\') {
            escaping = true;
            current.push_back(ch);
            continue;
        }
        if (escaping) {
            escaping = false;
        }
        current.push_back(ch);
    }
    fields.push_back(UnescapeField(current));
    return fields;
}

std::string NormalizePhoneLabel(std::string_view label) {
    std::string output;
    output.reserve(label.size());
    for (char ch : label) {
        if (std::isdigit(static_cast<unsigned char>(ch)) != 0) {
            continue;
        }
        output.push_back(static_cast<char>(std::toupper(static_cast<unsigned char>(ch))));
    }
    return output;
}

std::vector<std::string> NormalizeTokens(std::string_view text) {
    std::vector<std::string> tokens;
    std::string current;
    auto flush = [&]() {
        while (!current.empty() && current.front() == '\'') {
            current.erase(current.begin());
        }
        while (!current.empty() && current.back() == '\'') {
            current.pop_back();
        }
        if (!current.empty()) {
            tokens.push_back(current);
        }
        current.clear();
    };

    for (unsigned char raw : text) {
        const char ch = static_cast<char>(raw);
        if (ch == '-') {
            flush();
            continue;
        }
        if (std::isalpha(raw) != 0 || ch == '\'') {
            current.push_back(static_cast<char>(std::tolower(raw)));
        } else if (std::isdigit(raw)) {
            flush();
            static const std::array<const char*,10> digits={"zero","one","two","three","four","five","six","seven","eight","nine"};
            tokens.emplace_back(digits[raw-'0']);
        } else if (ch=='&') { flush(); tokens.emplace_back("and");
        } else {
            flush();
        }
    }
    flush();
    return tokens;
}

std::string JoinTokens(const std::vector<std::string>& tokens, std::string_view separator = " ") {
    if (tokens.empty()) {
        return {};
    }
    std::string joined = tokens.front();
    for (std::size_t index = 1; index < tokens.size(); ++index) {
        joined.append(separator);
        joined.append(tokens[index]);
    }
    return joined;
}

std::vector<std::string> SplitSpaceSeparated(std::string_view text) {
    std::vector<std::string> output;
    std::string current;
    for (const unsigned char raw : text) {
        if (std::isspace(raw) != 0) {
            if (!current.empty()) {
                output.push_back(current);
                current.clear();
            }
            continue;
        }
        current.push_back(static_cast<char>(raw));
    }
    if (!current.empty()) {
        output.push_back(current);
    }
    return output;
}

bool StartsWithAt(std::string_view text, std::size_t index, std::string_view pattern) {
    return index + pattern.size() <= text.size() && text.substr(index, pattern.size()) == pattern;
}

bool IsVowelLetter(char ch) {
    switch (ch) {
        case 'a':
        case 'e':
        case 'i':
        case 'o':
        case 'u':
        case 'y':
            return true;
        default:
            return false;
    }
}

std::vector<std::string> GuessPronunciation(std::string_view token) {
    std::string word;
    word.reserve(token.size());
    for (const unsigned char raw : token) {
        const char ch = static_cast<char>(std::tolower(raw));
        if (std::isalpha(raw) != 0 || ch == '\'') {
            word.push_back(ch);
        }
    }
    if (word.empty()) {
        return {};
    }

    std::vector<std::string> phones;
    const auto push = [&](std::string_view label) {
        phones.emplace_back(label);
    };

    std::size_t index = 0;
    while (index < word.size()) {
        const char ch = word[index];
        if (ch == '\'') {
            ++index;
            continue;
        }

        if (StartsWithAt(word, index, "tion")) {
            push("SH");
            push("AH");
            push("N");
            index += 4;
            continue;
        }
        if (StartsWithAt(word, index, "sion")) {
            push("ZH");
            push("AH");
            push("N");
            index += 4;
            continue;
        }
        if (StartsWithAt(word, index, "tch")) {
            push("CH");
            index += 3;
            continue;
        }
        if (StartsWithAt(word, index, "dge")) {
            push("JH");
            index += 3;
            continue;
        }
        if (StartsWithAt(word, index, "igh")) {
            push("AY");
            index += 3;
            continue;
        }
        if (StartsWithAt(word, index, "eigh")) {
            push("EY");
            index += 4;
            continue;
        }

        if (StartsWithAt(word, index, "sh")) {
            push("SH");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ch")) {
            push("CH");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "th")) {
            push("TH");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ph")) {
            push("F");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ng")) {
            push("NG");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "qu")) {
            push("K");
            push("W");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ck")) {
            push("K");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "wh")) {
            push("W");
            index += 2;
            continue;
        }
        if (index == 0 && StartsWithAt(word, index, "wr")) {
            push("R");
            index += 2;
            continue;
        }
        if (index == 0 && StartsWithAt(word, index, "kn")) {
            push("N");
            index += 2;
            continue;
        }
        if (index == 0 && StartsWithAt(word, index, "ps")) {
            push("S");
            index += 2;
            continue;
        }
        if (
            StartsWithAt(word, index, "ee") ||
            StartsWithAt(word, index, "ea") ||
            StartsWithAt(word, index, "ei")
        ) {
            push("IY");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "oo")) {
            push("UW");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "oa") || StartsWithAt(word, index, "oe") || StartsWithAt(word, index, "ow")) {
            push("OW");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ou")) {
            push("AW");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "oi") || StartsWithAt(word, index, "oy")) {
            push("OY");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ai") || StartsWithAt(word, index, "ay")) {
            push("EY");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "au") || StartsWithAt(word, index, "aw")) {
            push("AO");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "er") || StartsWithAt(word, index, "ir") || StartsWithAt(word, index, "ur")) {
            push("ER");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "ar")) {
            push("AA");
            push("R");
            index += 2;
            continue;
        }
        if (StartsWithAt(word, index, "or")) {
            push("AO");
            push("R");
            index += 2;
            continue;
        }

        if (
            index + 1 < word.size() &&
            word[index + 1] == ch &&
            !IsVowelLetter(ch) &&
            ch != 'r'
        ) {
            switch (ch) {
                case 's':
                    push("S");
                    break;
                case 'l':
                    push("L");
                    break;
                case 'm':
                    push("M");
                    break;
                case 'n':
                    push("N");
                    break;
                case 'p':
                    push("P");
                    break;
                case 't':
                    push("T");
                    break;
                case 'f':
                    push("F");
                    break;
                case 'g':
                    push("G");
                    break;
                default:
                    break;
            }
            index += 2;
            continue;
        }

        switch (ch) {
            case 'a':
                push(word.size() == 1 ? "EY" : "AE");
                break;
            case 'e':
                if (!(index + 1 == word.size() && word.size() > 1)) {
                    push("EH");
                }
                break;
            case 'i':
                push(index + 1 == word.size() ? "IY" : "IH");
                break;
            case 'o':
                if (index + 1 == word.size() || (index + 2 == word.size() && !IsVowelLetter(word[index + 1]))) {
                    push("OW");
                } else {
                    push("AA");
                }
                break;
            case 'u':
                push(index + 1 == word.size() ? "UW" : "AH");
                break;
            case 'y':
                push(index + 1 == word.size() ? "IY" : "Y");
                break;
            case 'b':
                push("B");
                break;
            case 'c':
                if (index + 1 < word.size() && (word[index + 1] == 'e' || word[index + 1] == 'i' || word[index + 1] == 'y')) {
                    push("S");
                } else {
                    push("K");
                }
                break;
            case 'd':
                push("D");
                break;
            case 'f':
                push("F");
                break;
            case 'g':
                if (index + 1 < word.size() && (word[index + 1] == 'e' || word[index + 1] == 'i' || word[index + 1] == 'y')) {
                    push("JH");
                } else {
                    push("G");
                }
                break;
            case 'h':
                push("HH");
                break;
            case 'j':
                push("JH");
                break;
            case 'k':
                push("K");
                break;
            case 'l':
                push("L");
                break;
            case 'm':
                push("M");
                break;
            case 'n':
                push("N");
                break;
            case 'p':
                push("P");
                break;
            case 'q':
                push("K");
                break;
            case 'r':
                push("R");
                break;
            case 's':
                push("S");
                break;
            case 't':
                push("T");
                break;
            case 'v':
                push("V");
                break;
            case 'w':
                push("W");
                break;
            case 'x':
                push("K");
                push("S");
                break;
            case 'z':
                push("Z");
                break;
            default:
                break;
        }
        ++index;
    }

    return phones;
}

std::vector<std::string> PhoneAlternatives(std::string_view label) {
    const std::string phone = NormalizePhoneLabel(label);
    if (phone == "IH") {
        return {"IH", "IY", "EH"};
    }
    if (phone == "IY") {
        return {"IY", "IH", "EH"};
    }
    if (phone == "EH") {
        return {"EH", "IH", "IY", "AE"};
    }
    if (phone == "AE") {
        return {"AE", "EH", "AH"};
    }
    if (phone == "AH") {
        return {"AH", "UH", "AA", "AE"};
    }
    if (phone == "AA") {
        return {"AA", "AH", "AO"};
    }
    if (phone == "AO") {
        return {"AO", "AA", "OW"};
    }
    if (phone == "UH") {
        return {"UH", "AH", "UW"};
    }
    if (phone == "UW") {
        return {"UW", "UH", "OW"};
    }
    if (phone == "OW") {
        return {"OW", "AO", "UW"};
    }
    if (phone == "EY") {
        return {"EY", "EH", "IY"};
    }
    if (phone == "AY") {
        return {"AY", "EY", "IH"};
    }
    return {phone};
}

std::string MakeKey(std::span<const std::string> values) {
    if (values.empty()) {
        return {};
    }
    std::string output = values.front();
    for (std::size_t index = 1; index < values.size(); ++index) {
        output.push_back(kKeySeparator);
        output.append(values[index]);
    }
    return output;
}

std::optional<double> ParseConfidence(std::string_view value) {
    if (value == "na" || value.empty()) {
        return std::nullopt;
    }
    return std::stod(std::string(value));
}

std::optional<double> MeanConfidence(const std::vector<std::optional<double>>& values) {
    double sum = 0.0;
    std::size_t count = 0;
    for (const auto& value : values) {
        if (!value.has_value()) {
            continue;
        }
        sum += *value;
        ++count;
    }
    if (count == 0) {
        return std::nullopt;
    }
    return sum / static_cast<double>(count);
}

double ConfidencePenalty(const std::optional<double>& confidence) {
    if (!confidence.has_value()) {
        return 0.2;
    }
    return std::max(0.0, 1.0 - *confidence) * 0.35;
}

template <typename T>
const T& PickBestOccurrence(const std::vector<T>& occurrences) {
    if (occurrences.empty()) {
        throw std::runtime_error("Expected at least one occurrence");
    }
    return *std::max_element(
        occurrences.begin(),
        occurrences.end(),
        [](const T& left, const T& right) {
            const double left_conf = left.confidence.value_or(0.0);
            const double right_conf = right.confidence.value_or(0.0);
            if (left_conf != right_conf) {
                return left_conf < right_conf;
            }
            const auto left_duration = left.end_sample - left.start_sample;
            const auto right_duration = right.end_sample - right.start_sample;
            return left_duration < right_duration;
        }
    );
}

std::uint16_t ReadU16(std::istream& input) {
    std::array<unsigned char, 2> bytes{};
    input.read(reinterpret_cast<char*>(bytes.data()), 2);
    if (!input) {
        throw std::runtime_error("Unexpected end of file while reading u16");
    }
    return static_cast<std::uint16_t>(bytes[0] | (bytes[1] << 8U));
}

std::uint32_t ReadU32(std::istream& input) {
    std::array<unsigned char, 4> bytes{};
    input.read(reinterpret_cast<char*>(bytes.data()), 4);
    if (!input) {
        throw std::runtime_error("Unexpected end of file while reading u32");
    }
    return static_cast<std::uint32_t>(
        bytes[0] |
        (bytes[1] << 8U) |
        (bytes[2] << 16U) |
        (bytes[3] << 24U)
    );
}

void AppendU16(std::vector<std::uint8_t>& output, std::uint16_t value) {
    output.push_back(static_cast<std::uint8_t>(value & 0xFFU));
    output.push_back(static_cast<std::uint8_t>((value >> 8U) & 0xFFU));
}

void AppendU32(std::vector<std::uint8_t>& output, std::uint32_t value) {
    output.push_back(static_cast<std::uint8_t>(value & 0xFFU));
    output.push_back(static_cast<std::uint8_t>((value >> 8U) & 0xFFU));
    output.push_back(static_cast<std::uint8_t>((value >> 16U) & 0xFFU));
    output.push_back(static_cast<std::uint8_t>((value >> 24U) & 0xFFU));
}

void AppendI16(std::vector<std::uint8_t>& output, std::int16_t value) {
    AppendU16(output, static_cast<std::uint16_t>(value));
}

WaveData LoadWavePcm16Mono(const std::filesystem::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        throw std::runtime_error("Could not open master WAV: " + path.string());
    }

    char riff[4];
    input.read(riff, 4);
    if (std::string_view(riff, 4) != "RIFF") {
        throw std::runtime_error("Expected RIFF header in WAV: " + path.string());
    }
    static_cast<void>(ReadU32(input));
    char wave[4];
    input.read(wave, 4);
    if (std::string_view(wave, 4) != "WAVE") {
        throw std::runtime_error("Expected WAVE header in WAV: " + path.string());
    }

    std::uint16_t audio_format = 0;
    std::uint16_t channel_count = 0;
    std::uint32_t sample_rate = 0;
    std::uint16_t bits_per_sample = 0;
    std::vector<std::int16_t> samples;

    while (input.peek() != std::char_traits<char>::eof()) {
        char chunk_id[4];
        input.read(chunk_id, 4);
        if (!input) {
            break;
        }
        const std::uint32_t chunk_size = ReadU32(input);
        const std::string_view chunk_name(chunk_id, 4);
        if (chunk_name == "fmt ") {
            audio_format = ReadU16(input);
            channel_count = ReadU16(input);
            sample_rate = ReadU32(input);
            static_cast<void>(ReadU32(input));
            static_cast<void>(ReadU16(input));
            bits_per_sample = ReadU16(input);
            if (chunk_size > 16) {
                input.seekg(static_cast<std::streamoff>(chunk_size - 16), std::ios::cur);
            }
        } else if (chunk_name == "data") {
            if ((chunk_size % 2U) != 0U) {
                throw std::runtime_error("Expected even-sized PCM data chunk");
            }
            const std::size_t sample_count = chunk_size / sizeof(std::int16_t);
            samples.resize(sample_count);
            input.read(reinterpret_cast<char*>(samples.data()), static_cast<std::streamsize>(chunk_size));
            if (!input) {
                throw std::runtime_error("Unexpected end of file while reading WAV sample data");
            }
        } else {
            input.seekg(static_cast<std::streamoff>(chunk_size), std::ios::cur);
        }
        if ((chunk_size % 2U) != 0U) {
            input.seekg(1, std::ios::cur);
        }
    }

    if (audio_format != 1 || channel_count != 1 || bits_per_sample != 16 || sample_rate == 0 || samples.empty()) {
        throw std::runtime_error("Expected mono 16-bit PCM WAV: " + path.string());
    }

    return WaveData{
        static_cast<std::int64_t>(sample_rate),
        std::move(samples),
    };
}

std::int16_t ClampI16(double value) {
    if (value < static_cast<double>(std::numeric_limits<std::int16_t>::min())) {
        return std::numeric_limits<std::int16_t>::min();
    }
    if (value > static_cast<double>(std::numeric_limits<std::int16_t>::max())) {
        return std::numeric_limits<std::int16_t>::max();
    }
    return static_cast<std::int16_t>(std::llround(value));
}

AcousticProfile EstimateAcousticProfile(
    const WaveData& wave,
    std::int64_t start_sample,
    std::int64_t end_sample
) {
    const auto bounded_start = std::max<std::int64_t>(0, start_sample);
    const auto bounded_end = std::min<std::int64_t>(
        std::max<std::int64_t>(bounded_start, end_sample),
        static_cast<std::int64_t>(wave.samples.size())
    );
    const auto total_length = bounded_end - bounded_start;
    if (total_length < 64) {
        return {};
    }

    const auto max_window = std::max<std::int64_t>(256, wave.sample_rate / 8);
    auto window_start = bounded_start;
    auto window_end = bounded_end;
    if (total_length > max_window) {
        const auto trim = (total_length - max_window) / 2;
        window_start += trim;
        window_end = window_start + max_window;
    }

    std::vector<double> centered;
    centered.reserve(static_cast<std::size_t>(window_end - window_start));
    double mean = 0.0;
    for (auto index = window_start; index < window_end; ++index) {
        mean += static_cast<double>(wave.samples[static_cast<std::size_t>(index)]) / 32768.0;
    }
    mean /= static_cast<double>(window_end - window_start);

    double energy = 0.0;
    for (auto index = window_start; index < window_end; ++index) {
        const double sample = static_cast<double>(wave.samples[static_cast<std::size_t>(index)]) / 32768.0 - mean;
        centered.push_back(sample);
        energy += sample * sample;
    }

    AcousticProfile profile;
    profile.rms = std::sqrt(energy / static_cast<double>(centered.size()));
    if (profile.rms < 0.01 || centered.size() < 128) {
        return profile;
    }

    const auto min_lag = std::max<std::int64_t>(1, wave.sample_rate / 420);
    const auto max_lag = std::min<std::int64_t>(
        static_cast<std::int64_t>(centered.size() / 2),
        wave.sample_rate / 70
    );
    if (max_lag <= min_lag) {
        return profile;
    }

    double best_correlation = 0.0;
    std::int64_t best_lag = 0;
    for (auto lag = min_lag; lag <= max_lag; ++lag) {
        double numerator = 0.0;
        double left_energy = 0.0;
        double right_energy = 0.0;
        for (std::size_t index = 0; index + static_cast<std::size_t>(lag) < centered.size(); ++index) {
            const double left = centered[index];
            const double right = centered[index + static_cast<std::size_t>(lag)];
            numerator += left * right;
            left_energy += left * left;
            right_energy += right * right;
        }
        if (left_energy <= 1e-9 || right_energy <= 1e-9) {
            continue;
        }
        const double correlation = numerator / std::sqrt(left_energy * right_energy);
        if (correlation > best_correlation) {
            best_correlation = correlation;
            best_lag = lag;
        }
    }

    if (best_lag > 0 && best_correlation >= 0.18) {
        profile.pitch_hz = static_cast<double>(wave.sample_rate) / static_cast<double>(best_lag);
    }
    return profile;
}

std::vector<std::uint8_t> WaveBytesFromSamples(const std::vector<std::int16_t>& samples, std::int64_t sample_rate) {
    if (samples.size() > (std::numeric_limits<std::uint32_t>::max()-44)/2) throw std::runtime_error("WAV exceeds RIFF size limit");
    const std::uint32_t data_size = static_cast<std::uint32_t>(samples.size() * sizeof(std::int16_t));
    std::vector<std::uint8_t> output;
    output.reserve(static_cast<std::size_t>(44 + data_size));

    output.insert(output.end(), {'R', 'I', 'F', 'F'});
    AppendU32(output, 36U + data_size);
    output.insert(output.end(), {'W', 'A', 'V', 'E'});
    output.insert(output.end(), {'f', 'm', 't', ' '});
    AppendU32(output, 16U);
    AppendU16(output, 1U);
    AppendU16(output, 1U);
    AppendU32(output, static_cast<std::uint32_t>(sample_rate));
    AppendU32(output, static_cast<std::uint32_t>(sample_rate * 2));
    AppendU16(output, 2U);
    AppendU16(output, 16U);
    output.insert(output.end(), {'d', 'a', 't', 'a'});
    AppendU32(output, data_size);
    for (const auto sample : samples) {
        AppendI16(output, sample);
    }
    return output;
}

#include "vcpack_reader.inc"
#include "pronunciation.inc"

}  // namespace

struct VoiceBank::Impl {
    std::filesystem::path bank_path;
    std::filesystem::path master_audio_path;
    std::string merc;
    std::string language = "en-us", report;
    std::uint32_t feature_hop{};
    std::vector<FeatureFrame> features;
    mutable std::recursive_mutex mutex;
    std::int64_t sample_rate = 0;
    std::vector<Record> records;
    std::unordered_map<std::string, std::vector<ChunkOccurrence>> chunk_index;
    std::unordered_map<std::string, std::vector<ChunkOccurrence>> word_index;
    std::unordered_map<std::string, std::vector<PhoneOccurrence>> phone_index;
    std::unordered_map<std::string, std::vector<std::string>> pronunciation_index;
    mutable std::unordered_map<std::string, AcousticProfile> acoustic_profile_cache;
    mutable std::optional<WaveData> master_wave;

    void build_pronunciation_index() {
        std::unordered_map<std::string, std::unordered_map<std::string, PronunciationStats>> candidates;
        for (const auto& record : records) {
            std::unordered_map<std::int64_t, std::vector<Phoneme>> by_word_index;
            for (const auto& phoneme : record.phonemes) {
                if (phoneme.word_index < 0) {
                    continue;
                }
                by_word_index[phoneme.word_index].push_back(phoneme);
            }

            for (auto& [word_index_value, phones] : by_word_index) {
                if (word_index_value < 0 || static_cast<std::size_t>(word_index_value) >= record.words.size()) {
                    continue;
                }
                std::sort(
                    phones.begin(),
                    phones.end(),
                    [](const Phoneme& left, const Phoneme& right) {
                        return left.start_sample < right.start_sample;
                    }
                );
                std::vector<std::string> labels;
                labels.reserve(phones.size());
                for (const auto& phoneme : phones) {
                    if (!phoneme.normalized_label.empty()) {
                        labels.push_back(phoneme.normalized_label);
                    }
                }
                if (labels.empty()) {
                    continue;
                }

                const auto& word = record.words[static_cast<std::size_t>(word_index_value)];
                if (word.text.empty()) {
                    continue;
                }

                auto& variants = candidates[word.text];
                const auto key = MakeKey(labels);
                auto& stats = variants[key];
                if (stats.labels.empty()) {
                    stats.labels = labels;
                }
                stats.count += 1;
                stats.confidence_sum += word.confidence.value_or(0.0);
            }
        }

        for (const auto& [word, variants] : candidates) {
            if (pronunciation_index.find(word) != pronunciation_index.end()) {
                continue;
            }

            const auto best = std::max_element(
                variants.begin(),
                variants.end(),
                [](const auto& left, const auto& right) {
                    if (left.second.count != right.second.count) {
                        return left.second.count < right.second.count;
                    }
                    if (left.second.confidence_sum != right.second.confidence_sum) {
                        return left.second.confidence_sum < right.second.confidence_sum;
                    }
                    return left.second.labels.size() < right.second.labels.size();
                }
            );
            if (best != variants.end()) {
                pronunciation_index[word] = best->second.labels;
            }
        }
    }

    void build_indexes() {
        for (const auto& record : records) {
            for (std::size_t start = 0; start < record.words.size(); ++start) {
                std::vector<std::string> tokens;
                std::vector<std::optional<double>> confidences;
                for (std::size_t length = 1;
                     length <= static_cast<std::size_t>(kIndexChunkWords) && start + length <= record.words.size();
                     ++length) {
                    const auto& word = record.words[start + length - 1];
                    tokens.push_back(word.text);
                    confidences.push_back(word.confidence);
                    ChunkOccurrence occurrence{
                        JoinTokens(tokens),
                        tokens,
                        record.clip_id,
                        record.words[start].start_sample,
                        word.end_sample,
                        MeanConfidence(confidences),
                    };
                    const auto key = MakeKey(tokens);
                    chunk_index[key].push_back(occurrence);
                    if (length == 1) {
                        word_index[tokens.front()].push_back(occurrence);
                    }
                }
            }

            std::unordered_map<std::int64_t, std::vector<Phoneme>> by_word_index;
            for (const auto& phoneme : record.phonemes) {
                if (phoneme.word_index < 0) {
                    continue;
                }
                by_word_index[phoneme.word_index].push_back(phoneme);
            }

            for (const auto& [word_index_value, phones] : by_word_index) {
                if (word_index_value < 0 || static_cast<std::size_t>(word_index_value) >= record.words.size()) {
                    continue;
                }
                for (std::size_t start = 0; start < phones.size(); ++start) {
                    std::vector<std::string> labels;
                    std::vector<std::optional<double>> confidences;
                    for (std::size_t length = 1;
                         length <= static_cast<std::size_t>(kIndexPhoneNgram) && start + length <= phones.size();
                         ++length) {
                        const auto& phoneme = phones[start + length - 1];
                        labels.push_back(phoneme.normalized_label);
                        confidences.push_back(phoneme.confidence);
                        PhoneOccurrence occurrence{
                            labels,
                            record.clip_id,
                            phones[start].start_sample,
                            phoneme.end_sample,
                            MeanConfidence(confidences),
                            record.words[static_cast<std::size_t>(word_index_value)].text,
                        };
                        phone_index[MakeKey(labels)].push_back(occurrence);
                    }
                }
            }
        }
    }

    void build_crossword_phones() {
        for(const auto& r:records) for(std::size_t i=0;i<r.phonemes.size();++i) {
            std::vector<std::string> labels;
            for(std::size_t n=0;n<12 && i+n<r.phonemes.size();++n) {
                const auto& p=r.phonemes[i+n];
                if(n && p.start_sample-r.phonemes[i+n-1].end_sample>sample_rate/50)break;
                labels.push_back(p.normalized_label);
                if(p.word_index==r.phonemes[i].word_index)continue;
                phone_index[MakeKey(labels)].push_back({labels,r.clip_id,r.phonemes[i].start_sample,p.end_sample,p.confidence,"cross-word sounds"});
            }
        }
    }

    const WaveData& ensure_master_wave() const {
        if (!master_wave.has_value()) {
            master_wave = LoadWavePcm16Mono(master_audio_path);
        }
        return *master_wave;
    }

    AcousticProfile profile_for_range(std::int64_t start_sample, std::int64_t end_sample) const {
        const auto key = std::to_string(start_sample) + ":" + std::to_string(end_sample);
        const auto found = acoustic_profile_cache.find(key);
        if (found != acoustic_profile_cache.end()) {
            return found->second;
        }
        auto profile = EstimateAcousticProfile(ensure_master_wave(), start_sample, end_sample);
        acoustic_profile_cache.emplace(key, profile);
        return profile;
    }

    template <typename T>
    double occurrence_score(
        const T& occurrence,
        const std::optional<PlannedUnit>& previous,
        std::int64_t word_group
    ) const {
        double score = occurrence.confidence.value_or(0.0) * 4.0;
        const double duration_seconds =
            static_cast<double>(std::max<std::int64_t>(0, occurrence.end_sample - occurrence.start_sample)) /
            static_cast<double>(sample_rate);
        score += std::min(duration_seconds, 0.35) * 0.15;

        if (!previous.has_value()) {
            return score;
        }

        const bool same_word =
            previous->word_group >= 0 &&
            word_group >= 0 &&
            previous->word_group == word_group;

        if (occurrence.clip_id == previous->clip_id) {
            score += same_word ? 0.45 : 0.2;
            const double gap_seconds =
                static_cast<double>(std::abs(occurrence.start_sample - previous->end_sample)) /
                static_cast<double>(sample_rate);
            score += std::max(0.0, (same_word ? 0.35 : 0.18) - gap_seconds * (same_word ? 0.9 : 0.45));
        }

        const auto previous_profile = profile_for_range(previous->start_sample, previous->end_sample);
        const auto current_profile = profile_for_range(occurrence.start_sample, occurrence.end_sample);

        if (previous_profile.pitch_hz.has_value() &&
            current_profile.pitch_hz.has_value() &&
            *previous_profile.pitch_hz > 0.0 &&
            *current_profile.pitch_hz > 0.0) {
            const double semitone_delta =
                std::abs(12.0 * std::log(*current_profile.pitch_hz / *previous_profile.pitch_hz) / std::log(2.0));
            score -= semitone_delta * (same_word ? 0.09 : 0.06);
        }

        if (previous_profile.rms > 1e-4 && current_profile.rms > 1e-4) {
            const double rms_delta_db =
                std::abs(20.0 * std::log10(current_profile.rms / previous_profile.rms));
            score -= rms_delta_db * (same_word ? 0.025 : 0.015);
        }

        return score;
    }

    template <typename T>
    const T& pick_best_occurrence(
        const std::vector<T>& occurrences,
        const std::optional<PlannedUnit>& previous,
        std::int64_t word_group
    ) const {
        if (occurrences.empty()) {
            throw std::runtime_error("Expected at least one occurrence");
        }
        return *std::max_element(
            occurrences.begin(),
            occurrences.end(),
            [&](const T& left, const T& right) {
                const double left_score = occurrence_score(left, previous, word_group);
                const double right_score = occurrence_score(right, previous, word_group);
                if (left_score != right_score) {
                    return left_score < right_score;
                }
                const double left_conf = left.confidence.value_or(0.0);
                const double right_conf = right.confidence.value_or(0.0);
                if (left_conf != right_conf) {
                    return left_conf < right_conf;
                }
                const auto left_duration = left.end_sample - left.start_sample;
                const auto right_duration = right.end_sample - right.start_sample;
                return left_duration < right_duration;
            }
        );
    }
};

VoiceBank VoiceBank::Load(const std::filesystem::path& bank_path) {
    if (bank_path.extension() == ".vcpack") {
        auto packed = ReadVcpack(bank_path);
        auto impl = std::make_unique<Impl>();
        impl->bank_path = std::filesystem::absolute(bank_path);
        impl->merc = std::move(packed.voice); impl->language = std::move(packed.language);
        impl->report = std::move(packed.report); impl->sample_rate = packed.wave.sample_rate;
        impl->master_wave = std::move(packed.wave); impl->records = std::move(packed.records);
        impl->pronunciation_index = std::move(packed.lexicon);
        impl->feature_hop = packed.hop; impl->features = std::move(packed.features);
        impl->build_pronunciation_index(); impl->build_indexes(); impl->build_crossword_phones();
        VoiceBank bank; bank.impl_ = impl.release(); return bank;
    }
    std::ifstream input(bank_path);
    if (!input) {
        throw std::runtime_error("Could not open bank file: " + bank_path.string());
    }

    auto owner = std::make_unique<Impl>();
    auto impl = owner.get();
    impl->bank_path = std::filesystem::absolute(bank_path);

    std::string line;
    if (!std::getline(input, line)) {
        throw std::runtime_error("Empty bank file: " + bank_path.string());
    }
    {
        const auto header = SplitEscapedTabs(line);
        if (header.size() != 2 || header[0] != kPackageMagic) {
                throw std::runtime_error("Unsupported bank header: " + bank_path.string());
        }
        const int version = std::stoi(header[1]);
        if (version != 1 && version != kPackageVersion) {
                throw std::runtime_error("Unsupported bank header: " + bank_path.string());
        }
    }

    std::optional<Record> current_record;
    while (std::getline(input, line)) {
        if (line.empty()) {
            continue;
        }
        const auto fields = SplitEscapedTabs(line);
        if (fields.empty()) {
            continue;
        }
        const auto& tag = fields[0];
        if (tag == "merc" && fields.size() >= 2) {
            impl->merc = fields[1];
            continue;
        }
        if (tag == "sample_rate" && fields.size() >= 2) {
            impl->sample_rate = std::stoi(fields[1]);
            continue;
        }
        if (tag == "master_audio" && fields.size() >= 2) {
            std::filesystem::path master = fields[1];
            if (master.is_relative()) {
                master = impl->bank_path.parent_path() / master;
            }
            impl->master_audio_path = std::filesystem::absolute(master);
            continue;
        }
        if (tag == "lexicon" && fields.size() >= 3) {
            auto phones = SplitSpaceSeparated(fields[2]);
            std::vector<std::string> normalized;
            normalized.reserve(phones.size());
            for (const auto& phone : phones) {
                const auto label = NormalizePhoneLabel(phone);
                if (!label.empty()) {
                    normalized.push_back(label);
                }
            }
            if (!fields[1].empty() && !normalized.empty()) {
                impl->pronunciation_index[fields[1]] = std::move(normalized);
            }
            continue;
        }
        if (tag == "record" && fields.size() >= 2) {
            if (current_record.has_value()) {
                impl->records.push_back(std::move(*current_record));
            }
            current_record = Record{};
            current_record->clip_id = fields[1];
            continue;
        }
        if (tag == "word" && fields.size() >= 5) {
            if (!current_record.has_value()) {
                        throw std::runtime_error("Encountered word entry outside record");
            }
            current_record->words.push_back(Word{
                fields[1],
                std::stoi(fields[2]),
                std::stoi(fields[3]),
                ParseConfidence(fields[4]),
            });
            continue;
        }
        if (tag == "phoneme" && fields.size() >= 6) {
            if (!current_record.has_value()) {
                        throw std::runtime_error("Encountered phoneme entry outside record");
            }
            current_record->phonemes.push_back(Phoneme{
                fields[1],
                NormalizePhoneLabel(fields[1]),
                std::stoi(fields[2]),
                std::stoi(fields[3]),
                std::stoi(fields[4]),
                ParseConfidence(fields[5]),
            });
            continue;
        }
        if (tag == "endrecord") {
            if (current_record.has_value()) {
                impl->records.push_back(std::move(*current_record));
                current_record.reset();
            }
        }
    }
    if (current_record.has_value()) {
        impl->records.push_back(std::move(*current_record));
    }

    if (impl->merc.empty() || impl->sample_rate <= 0 || impl->master_audio_path.empty() || impl->records.empty()) {
        throw std::runtime_error("Incomplete bank file: " + bank_path.string());
    }

    impl->build_pronunciation_index();
    impl->build_indexes(); impl->build_crossword_phones();

    VoiceBank bank;
    bank.impl_ = owner.release();
    return bank;
}

VoiceBank::VoiceBank(VoiceBank&& other) noexcept : impl_(std::exchange(other.impl_, nullptr)) {}

VoiceBank& VoiceBank::operator=(VoiceBank&& other) noexcept {
    if (this == &other) {
        return *this;
    }
    delete impl_;
    impl_ = std::exchange(other.impl_, nullptr);
    return *this;
}

VoiceBank::~VoiceBank() {
    delete impl_;
}

const std::string& VoiceBank::quality_report() const noexcept { return impl_->report; }

const std::string& VoiceBank::merc() const noexcept {
    assert(impl_ != nullptr);
    return impl_->merc;
}

std::int64_t VoiceBank::sample_rate() const noexcept {
    assert(impl_ != nullptr);
    return impl_->sample_rate;
}

const std::filesystem::path& VoiceBank::master_audio_path() const noexcept {
    assert(impl_ != nullptr);
    return impl_->master_audio_path;
}

#include "planner.inc"

PlanResult VoiceBank::PlanPhonemes(const std::vector<std::string>& phones, const SynthesizeOptions& options) const {
    std::lock_guard guard(impl_->mutex);
    if(phones.empty())throw std::runtime_error("Expected at least one phoneme");
    const std::string key="phonomenalexplicitphones";
    const auto old=impl_->pronunciation_index.find(key);
    const std::optional<std::vector<std::string>> previous=old==impl_->pronunciation_index.end()?std::nullopt:std::optional(old->second);
    impl_->pronunciation_index[key]=phones;
    auto restore=[&]{if(previous)impl_->pronunciation_index[key]=*previous;else impl_->pronunciation_index.erase(key);};
    try {auto result=PlanText(key,options);restore();result.input_text=JoinTokens(phones);result.normalized_text=result.input_text;return result;}
    catch(...){restore();throw;}
}

std::vector<std::uint8_t> VoiceBank::SynthesizeWav(const PlanResult& plan, const SynthesizeOptions& options) const {
    std::lock_guard guard(impl_->mutex);
    assert(impl_ != nullptr);
    const auto& wave = impl_->ensure_master_wave();
    if (wave.sample_rate != plan.sample_rate) {
        throw std::runtime_error("Plan sample rate does not match master audio sample rate");
    }

    const std::int64_t overlap = std::max<std::int64_t>(
        0,
        static_cast<std::int64_t>(std::llround(
            static_cast<double>(wave.sample_rate) * static_cast<double>(options.crossfade_ms) / 1000.0
        ))
    );
    const std::int64_t word_gap = std::max<std::int64_t>(
        0,
        static_cast<std::int64_t>(std::llround(
            static_cast<double>(wave.sample_rate) * static_cast<double>(options.word_gap_ms) / 1000.0
        ))
    );

    std::vector<std::int16_t> output;
    const PlannedUnit* previous = nullptr;
    for (const auto& unit : plan.units) {
        if(options.stop_token.stop_requested())throw std::runtime_error("Synthesis cancelled");
        const auto start = std::max<std::int64_t>(0, unit.start_sample);
        const auto end = std::max<std::int64_t>(start, unit.end_sample);
        if (static_cast<std::size_t>(end) > wave.samples.size()) {
            throw std::runtime_error("Planned unit exceeds master WAV sample bounds");
        }
        std::vector<std::int16_t> segment(wave.samples.begin() + start, wave.samples.begin() + end);
        if (segment.empty()) {
            continue;
        }
        if (previous != nullptr &&
            word_gap > 0 &&
            previous->word_group >= 0 &&
            unit.word_group >= 0 &&
            previous->word_group != unit.word_group) {
            output.insert(output.end(), static_cast<std::size_t>(word_gap), 0);
        }
        if (unit.pause_before_ms>0 && previous!=nullptr) {
            output.insert(output.end(),static_cast<std::size_t>(wave.sample_rate*unit.pause_before_ms/1000),0);
            output.insert(output.end(),segment.begin(),segment.end());previous=&unit;continue;
        }
        if (output.empty() || overlap <= 0 || (previous && previous->clip_id==unit.clip_id && previous->end_sample==unit.start_sample)) {
            output.insert(output.end(), segment.begin(), segment.end());
            previous = &unit;
            continue;
        }

        const std::int64_t actual_overlap = std::min<std::int64_t>(
            overlap,
            std::min<std::int64_t>(
                static_cast<std::int64_t>(output.size()),
                static_cast<std::int64_t>(segment.size() / 4)
            )
        );
        if (actual_overlap <= 0) {
            output.insert(output.end(), segment.begin(), segment.end());
            previous = &unit;
            continue;
        }

        const auto prefix_size = output.size() - static_cast<std::size_t>(actual_overlap);
        std::vector<std::int16_t> merged;
        merged.reserve(prefix_size + static_cast<std::size_t>(actual_overlap) + segment.size());
        merged.insert(merged.end(), output.begin(), output.begin() + static_cast<std::ptrdiff_t>(prefix_size));

        if (actual_overlap == 1) {
            merged.push_back(ClampI16((static_cast<double>(output.back()) + static_cast<double>(segment.front())) / 2.0));
        } else {
            for (std::int64_t index = 0; index < actual_overlap; ++index) {
                const double blend = static_cast<double>(index) / static_cast<double>(actual_overlap - 1);
                const double left_gain = std::sqrt(std::max(0.0, 1.0 - blend));
                const double right_gain = std::sqrt(blend);
                const auto left = output[prefix_size + static_cast<std::size_t>(index)];
                const auto right = segment[static_cast<std::size_t>(index)];
                merged.push_back(ClampI16(static_cast<double>(left) * left_gain + static_cast<double>(right) * right_gain));
            }
        }

        merged.insert(merged.end(), segment.begin() + static_cast<std::ptrdiff_t>(actual_overlap), segment.end());
        output = std::move(merged);
        previous = &unit;
    }

    return WaveBytesFromSamples(output, wave.sample_rate);
}

std::string UnitKindToString(UnitKind kind) {
    switch (kind) {
        case UnitKind::ExactChunk:
            return "exact_chunk";
        case UnitKind::ExactWord:
            return "exact_word";
        case UnitKind::WordPiece:
            return "word_piece";
        case UnitKind::Phoneme:
            return "phoneme";
    }
    return "unknown";
}

}  // namespace phonomenal_splicer
