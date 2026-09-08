// Duration-preserving pitch correction: resampling followed by waveform-similarity
// overlap-add (WSOLA). Voiced chunks only; no generated/replacement voice audio.
static std::vector<std::int16_t> ShiftPitchPreserveDuration(
    const std::vector<std::int16_t> &input, double factor, std::int64_t rate) {
  if (input.size() < 32 || std::abs(factor - 1.) < .005) return input;
  factor = std::clamp(factor, .5, 2.);
  const auto count = input.size();
  const auto stretched_count = std::max<std::size_t>(2, std::llround(count / factor));
  std::vector<double> resampled(stretched_count);
  for (std::size_t i = 0; i < stretched_count; ++i) {
    const double position = std::min<double>(count - 1, i * factor);
    const auto base = static_cast<std::size_t>(position);
    const double fraction = position - base;
    resampled[i] = input[base] * (1. - fraction) + input[std::min(base + 1, count - 1)] * fraction;
  }
  const int window = std::max(16, std::min<int>(rate * .04, std::min(count, stretched_count)));
  const int hop = std::max(8, window / 2);
  const int search = std::max(8, static_cast<int>(rate * .012));
  std::vector<double> output(count + window, 0.), weights(output.size(), 0.);
  for (std::size_t position = 0; position < count; position += hop) {
    const int maximum = std::max(0, static_cast<int>(stretched_count) - window);
    const int expected = std::clamp<int>(std::llround(position / factor), 0, maximum);
    int selected = expected;
    if (position) {
      double best = -2.;
      for (int candidate = std::max(0, expected - search); candidate <= std::min(maximum, expected + search); candidate += 2) {
        double xy=0., xx=0., yy=0.;
        for (int j = 0; j < hop && position + j < count; j += 8) {
          const double x=weights[position+j]>.0001 ? output[position+j]/weights[position+j] : 0.;
          const double y=resampled[candidate+j];
          xy+=x*y;xx+=x*x;yy+=y*y;
        }
        const double correlation = xy/std::sqrt(std::max(1.,xx*yy)) - .015*std::abs(candidate-expected)/search;
        if (correlation>best) {best=correlation;selected=candidate;}
      }
    }
    for (int j=0;j<window && position+j<count;++j) {
      // Half-sample offset avoids a zero-weight first/last sample.
      const double weight=.5-.5*std::cos(2.*3.141592653589793*(j+.5)/window);
      output[position+j]+=resampled[std::min<std::size_t>(selected+j,stretched_count-1)]*weight;
      weights[position+j]+=weight;
    }
  }
  std::vector<std::int16_t> result(count);
  for (std::size_t i=0;i<count;++i) result[i]=ClampI16(weights[i]>.0000001 ? output[i]/weights[i] : input[i]);
  return result;
}
