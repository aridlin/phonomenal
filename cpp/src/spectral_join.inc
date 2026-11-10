// Internal source-envelope descriptor. No resampling or modification of audio.
struct JoinEnvelope {
  bool valid = false;
  std::array<double, 12> cepstrum{};
};

JoinEnvelope SourceJoinEnvelope(std::span<const std::int16_t> pcm,
                                std::int64_t rate) {
  JoinEnvelope result;
  if (rate < 8000 || rate > 192000 || pcm.size() != static_cast<std::size_t>(rate / 25))
    return result;
  const auto count = pcm.size();
  double mean = 0.;
  for (const auto sample : pcm) mean += sample / 32768.;
  mean /= count;
  double energy = 0.;
  for (const auto sample : pcm) {
    const double value = sample / 32768. - mean;
    energy += value * value;
  }
  if (std::sqrt(energy / count) < .003) return result;
  std::size_t size = 1;
  while (size < count) size *= 2;
  std::vector<std::complex<double>> fft(size);
  const double pi = std::acos(-1.);
  const double alpha = std::pow(.97, 16000. / rate);
  double previous = 0.;
  for (std::size_t i = 0; i < count; ++i) {
    const double value = pcm[i] / 32768. - mean;
    fft[i] = (value - alpha * previous) * (.5 - .5 * std::cos(2. * pi * i / (count - 1)));
    previous = value;
  }
  // Iterative radix-2 FFT; all temporary state belongs to this descriptor.
  for (std::size_t i = 1, j = 0; i < size; ++i) {
    auto bit = size >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) std::swap(fft[i], fft[j]);
  }
  for (std::size_t width = 2; width <= size; width *= 2) {
    const auto step = std::polar(1., -2. * pi / width);
    for (std::size_t start = 0; start < size; start += width) {
      std::complex<double> phase = 1.;
      for (std::size_t j = 0; j < width / 2; ++j) {
        const auto even = fft[start + j];
        const auto odd = fft[start + j + width / 2] * phase;
        fft[start + j] = even + odd;
        fft[start + j + width / 2] = even - odd;
        phase *= step;
      }
    }
  }
  double total = 0.;
  for (std::size_t i = 0; i <= size / 2; ++i) total += std::norm(fft[i]);
  if (total <= 0. || !std::isfinite(total)) return result;
  auto mel = [](double hz) { return 2595. * std::log10(1. + hz / 700.); };
  const double low = mel(80.), high = mel(std::min(7600., rate * .475));
  std::array<double, 26> knots{};
  for (std::size_t i = 0; i < knots.size(); ++i)
    knots[i] = 700. * (std::pow(10., (low + (high - low) * i / 25.) / 2595.) - 1.);
  std::array<double, 24> bands{};
  for (std::size_t band = 0; band < bands.size(); ++band) {
    double power = 0.;
    for (std::size_t bin = 0; bin <= size / 2; ++bin) {
      const double hz = static_cast<double>(bin) * rate / size;
      if (hz <= knots[band] || hz >= knots[band + 2]) continue;
      const double weight = hz <= knots[band + 1] ?
        (hz - knots[band]) / (knots[band + 1] - knots[band]) :
        (knots[band + 2] - hz) / (knots[band + 2] - knots[band + 1]);
      power += weight * std::norm(fft[bin]);
    }
    bands[band] = std::log(std::max(power / total, 1e-10));
  }
  for (std::size_t c = 0; c < result.cepstrum.size(); ++c) {
    for (std::size_t band = 0; band < bands.size(); ++band)
      result.cepstrum[c] += bands[band] * std::cos(pi * (c + 1) * (band + .5) / bands.size());
    result.cepstrum[c] *= std::sqrt(2. / bands.size());
  }
  result.valid = true;
  return result;
}

double JoinEnvelopeDistance(const JoinEnvelope &a, const JoinEnvelope &b) {
  double squared = 0.;
  for (std::size_t i = 0; i < a.cepstrum.size(); ++i) {
    const double difference = a.cepstrum[i] - b.cepstrum[i];
    squared += difference * difference;
  }
  return std::sqrt(squared / a.cepstrum.size());
}
