#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <cstdint>
#include <iostream>
#include <span>
#include <vector>
#include "../src/spectral_join.inc"

int main() {
  auto check = [](bool condition, const char *message) {
    if (!condition) { std::cerr << message << '\n'; return false; }
    return true;
  };
  // Same pitch, different harmonic envelopes; PCM scaling and DC are
  // independent recording-level properties, not a different vowel identity.
  for (const int rate : {8000, 16000, 22050, 44100, 48000, 96000}) {
    std::vector<std::int16_t> original(rate / 25), scaled(original.size()), dc(original.size()), different(original.size());
    const double pi = std::acos(-1.);
    for (std::size_t i = 0; i < original.size(); ++i) {
      const double phase = 2. * pi * 200. * i / rate;
      original[i] = static_cast<std::int16_t>(5000. * (std::sin(phase) + .5 * std::sin(3. * phase) + .25 * std::sin(7. * phase)));
      scaled[i] = original[i] * 2;
      dc[i] = original[i] + 2000;
      different[i] = static_cast<std::int16_t>(5000. * (.25 * std::sin(phase) + .5 * std::sin(3. * phase) + std::sin(7. * phase)));
    }
    const auto a = SourceJoinEnvelope(original, rate), b = SourceJoinEnvelope(scaled, rate),
               c = SourceJoinEnvelope(dc, rate), d = SourceJoinEnvelope(different, rate);
    if (!check(a.valid && b.valid && c.valid && d.valid, "Valid voiced signals rejected") ||
        !check(JoinEnvelopeDistance(a, a) == 0., "Identical signals differ") ||
        !check(JoinEnvelopeDistance(a, b) < 1e-10, "Gain changed vowel envelope") ||
        !check(JoinEnvelopeDistance(a, c) < 1e-10, "DC changed vowel envelope") ||
        !check(JoinEnvelopeDistance(a, d) > .1, "Different harmonic envelopes collapsed")) return 1;
    std::fill(original.begin(), original.end(), 2000);
    if (!check(!SourceJoinEnvelope(original, rate).valid, "DC accepted as speech")) return 1;
    for (std::size_t i = 0; i < original.size(); ++i) original[i] = i % 2 ? 10 : -10;
    if (!check(!SourceJoinEnvelope(original, rate).valid, "Subthreshold noise accepted")) return 1;
    original.pop_back();
    if (!check(!SourceJoinEnvelope(original, rate).valid, "Wrong window length accepted")) return 1;
  }
  if (!check(!SourceJoinEnvelope({}, 0).valid && !SourceJoinEnvelope({}, 384000).valid,
             "Unsupported input accepted")) return 1;
  return 0;
}
