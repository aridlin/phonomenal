PlanResult VoiceBank::PlanText(std::string_view text,
                               const SynthesizeOptions &options) const {
  std::lock_guard guard(impl_->mutex);
  if (text.size() > 16384)
    throw std::runtime_error(
        "Prompt exceeds 16384 UTF-8 bytes; split into sentences");
  const double center_join_cost=options.center_join_cost.value_or(impl_->center_join_cost);
  if(!std::isfinite(center_join_cost) || center_join_cost<0. || center_join_cost>1000.)
    throw std::runtime_error("Center join cost must be finite and between 0 and 1000");
  const auto spoken = TokenizeText(text);
  const auto &tokens = spoken.tokens;
  if (tokens.empty() || tokens.size() > 512)
    throw std::runtime_error("Expected 1 to 512 spoken words");
  const auto &pauses = spoken.pauses;
  std::vector<std::string> target, stressed_target;
  std::vector<std::size_t> starts, ends, word_at;
  std::vector<std::string> warnings;
  for (std::size_t w = 0; w < tokens.size(); ++w) {
    if (options.stop_token.stop_requested())
      throw std::runtime_error("Synthesis cancelled");
    starts.push_back(target.size());
    std::vector<std::string> pronunciation;
    auto it = impl_->pronunciation_index.find(tokens[w]);
    if (it != impl_->pronunciation_index.end())
      pronunciation = it->second;
    else {
      pronunciation = NativePronunciation(tokens[w]);
      if (pronunciation.empty()) {
        if (options.strict)
          throw std::runtime_error(
              "No pronunciation for '" + tokens[w] +
              "'; install eSpeak NG or provide a lexicon/phones");
        pronunciation = GuessPronunciation(tokens[w]);
        warnings.push_back("Heuristic pronunciation: " + tokens[w]);
      }
    }
    if (pronunciation.empty())
      throw std::runtime_error("Cannot pronounce '" + tokens[w] + "'");
    for (const auto &phone : pronunciation) {
      target.push_back(NormalizePhoneLabel(phone));
      stressed_target.push_back(phone);
      word_at.push_back(w);
    }
    ends.push_back(target.size());
  }
  if (target.size() > 4096)
    throw std::runtime_error("Prompt exceeds phone limit");
  struct Edge {
    std::size_t end;
    PlannedUnit unit;
    double penalty{};
  };
  std::vector<std::vector<Edge>> edges(target.size());
  std::vector<bool> recorded_word(tokens.size(), false);
  auto band_cost = [&](double pitch) {
    if (pitch<=0 || options.pitch_floor_hz<=0 || options.pitch_ceiling_hz<options.pitch_floor_hz) return 0.;
    const double wanted=std::clamp(pitch,options.pitch_floor_hz,options.pitch_ceiling_hz);
    // Prefer source audio close to the band before considering a small edit.
    return std::min(60.,std::abs(12.*std::log2(wanted/pitch))*2.);
  };
  // Match source token runs on demand: no hard four/eight-word phrase ceiling
  // and no quadratic phrase index.
  for (std::size_t w = 0; w < tokens.size(); ++w) {
    if (options.stop_token.stop_requested())
      throw std::runtime_error("Synthesis cancelled");
    for (const auto &record : impl_->records) {
      for (std::size_t rs = 0; rs < record.words.size(); ++rs) {
        if (record.words[rs].text != tokens[w])
          continue;
        for (std::size_t n = 0;
             w + n < tokens.size() && rs + n < record.words.size() &&
             n < static_cast<std::size_t>(
                     std::max<std::int64_t>(1, options.max_chunk_words));
             ++n) {
          if (record.words[rs + n].text != tokens[w + n] ||
              (n && pauses[w + n] > 0))
            break;
          const auto &first = record.words[rs];
          const auto &last = record.words[rs + n];
          PlannedUnit u{
              n ? UnitKind::ExactChunk : UnitKind::ExactWord,
              JoinTokens(std::vector<std::string>(
                  tokens.begin() + static_cast<std::ptrdiff_t>(w),
                  tokens.begin() + static_cast<std::ptrdiff_t>(w + n + 1))),
              "",
              {},
              record.clip_id,
              first.start_sample,
              last.end_sample,
              static_cast<std::int64_t>(w),
              last.confidence};
          u.pause_before_ms = pauses[w];
          u.end_word_group=static_cast<std::int64_t>(w+n);
          u.text = u.target_text;
          // Exact spelling does not make a bad alignment safe. Apply the same
          // acoustic-duration checks to words/phrases as to fallback phones.
          double boundary_penalty = 0.;
          double pitch_penalty=0.;
          std::size_t pitched_phones=0;
          bool suspect_boundary = false;
          for (const auto &phone : record.phonemes) {
            if (phone.start_sample < first.start_sample || phone.end_sample > last.end_sample) continue;
            const double penalty = impl_->phone_duration_penalty(phone);
            // Internal cuts are not exposed when a recorded word is kept.
            // A short aligned vowel alone must not force that word to be
            // rebuilt from unrelated recordings.
            boundary_penalty += penalty * .20;
            const double quality = impl_->acoustic_penalty(phone);
            boundary_penalty += std::isfinite(quality) ? quality * .35 : quality;
            if(phone.acoustic.voiced>=.7 && phone.acoustic.pitch>0) {pitch_penalty+=band_cost(phone.acoustic.pitch);++pitched_phones;}
            suspect_boundary = suspect_boundary || penalty >= 180.;
          }
          if (!std::isfinite(boundary_penalty) || (options.strict && suspect_boundary)) continue;
          if(pitched_phones) boundary_penalty+=pitch_penalty/pitched_phones;
          if(n==0 && boundary_penalty<180.) recorded_word[w]=true;
          edges[starts[w]].push_back({ends[w + n], std::move(u), boundary_penalty});
        }
      }
    }
  }
  for (std::size_t i = 0; i < target.size(); ++i) {
    if (options.stop_token.stop_requested())
      throw std::runtime_error("Synthesis cancelled");
    const auto max_len =
        std::min<std::size_t>(static_cast<std::size_t>(std::max<std::int64_t>(
                                  1, options.max_phone_ngram)),
                              target.size() - i);
    for (std::size_t len = 1; len <= max_len; ++len) {
      const auto last_word = word_at[i + len - 1];
      if (last_word != word_at[i] && pauses[last_word] > 0)
        break;
      const auto key =
          MakeKey(std::span<const std::string>(target.data() + i, len));
      auto found = impl_->phone_index.find(key);
      bool approximated = false;
      if (found == impl_->phone_index.end() && len == 1 && !options.strict) {
        for (const auto &alt : PhoneAlternatives(target[i])) {
          auto candidate = impl_->phone_index.find(alt);
          if (candidate != impl_->phone_index.end()) {
            found = candidate;
            approximated = true;
            break;
          }
        }
      }
      if (found == impl_->phone_index.end())
        continue;
      for (const auto &p : found->second) {
        // Strict mode also excludes obviously collapsed/stretched phone cuts.
        if (!std::isfinite(p.acoustic_penalty) || (options.strict && p.duration_penalty >= 180.))
          continue;
        double stress_penalty = 0.;
        for (std::size_t n = 0; n < len && n < p.stressed_labels.size(); ++n) {
          const auto &wanted = stressed_target[i + n];
          const auto &actual = p.stressed_labels[n];
          if (!wanted.empty() && !actual.empty() &&
              (wanted.back() == '1' || wanted.back() == '2') &&
              actual.back() == '0')
            stress_penalty += 90.;
        }
        // An emphatic, sentence-final vowel can be far too long inside a new
        // compound. Prefer an occurrence closer to ordinary syllable timing.
        double expected_ms = 0.;
        for (std::size_t n = 0; n < len; ++n) {
          const auto &phone = target[i + n];
          const bool vowel =
              std::string(" AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW ")
                  .find(" " + phone + " ") != std::string::npos;
          expected_ms +=
              vowel ? (stressed_target[i + n].back() == '1' ? 180. : 140.)
                    : (phone == "HH" ? 45. : 70.);
        }
        const double duration_ms =
            1000. * (p.end_sample - p.start_sample) / impl_->sample_rate;
        const double timing_penalty =
            std::max(0., duration_ms - expected_ms * 1.7) * .8;
        PlannedUnit u{UnitKind::Phoneme, tokens[word_at[i]],
                      p.source_word,     p.labels,
                      p.clip_id,         p.start_sample,
                      p.end_sample,      static_cast<std::int64_t>(word_at[i]),
                      p.confidence};
        u.target_text = JoinTokens(std::vector<std::string>(
            tokens.begin() + static_cast<std::ptrdiff_t>(word_at[i]),
            tokens.begin() + static_cast<std::ptrdiff_t>(last_word + 1)));
        u.pause_before_ms = (i == starts[word_at[i]]) ? pauses[word_at[i]] : 0;
        u.approximated = approximated;
        u.end_word_group=static_cast<std::int64_t>(last_word);
        double discarded_words=0.;
        for(std::size_t n=0;n<len;++n)
          if(recorded_word[word_at[i+n]]) discarded_words+=35.;
        edges[i].push_back(
            {i + len, std::move(u),
             .15 * static_cast<double>(len) + p.duration_penalty +
                 stress_penalty + timing_penalty + p.acoustic_penalty + band_cost(p.pitch) + discarded_words +
                 100. * static_cast<double>(last_word-word_at[i]) +
                 (i>0 && !p.left_context.empty() && p.left_context!=target[i-1] ? 12. : 0.) +
                 (i+len<target.size() && !p.right_context.empty() && p.right_context!=target[i+len] ? 12. : 0.) +
                 (i + len == ends[last_word] && !p.ends_word ? 180. : 0.) +
                 (i == starts[word_at[i]] && !p.begins_word ? 50. : 0.) +
                 (p.whole_word ? 0. : 70.) + (approximated ? 1000000. : 0.)});
      }
    }
  }
  if(options.center_phone_joins) {
    auto joinable=[](const std::string &label) {
      // A closure and a release are different events. Joining two arbitrary
      // halves of a stop/affricate can duplicate or remove its burst.
      return std::string(" AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW M N NG L R W Y F V S Z SH ZH TH DH ")
          .find(" "+label+" ")!=std::string::npos;
    };
    std::vector<std::vector<Edge>> expanded(target.size()*2);
    for(std::size_t i=0;i<edges.size();++i)
      for(auto &edge:edges[i]) {edge.end*=2;expanded[i*2].push_back(std::move(edge));}
    edges=std::move(expanded);
    for(std::size_t i=0;i<target.size();++i) {
      if(options.stop_token.stop_requested()) throw std::runtime_error("Synthesis cancelled");
      const auto max_run=std::clamp<std::size_t>(options.center_max_phone_run,2,12);
      for(std::size_t length=1;length<=max_run && i+length<=target.size();++length) {
        const auto last=i+length-1,first_word=word_at[i],last_word=word_at[last];
        const bool first_center=joinable(target[i]),last_center=joinable(target[last]);
        if(!first_center && !last_center) continue;
        if(length>=2 && first_word!=last_word && pauses[last_word]>0) break;
        const auto &index=length<=2?impl_->center_index:impl_->phone_index;
        const auto found=index.find(MakeKey(std::span<const std::string>(target.data()+i,length)));
        if(found==index.end()) continue;
        for(const auto &p:found->second) {
          if(length>2 && !p.continuous) continue;
          if(!std::isfinite(p.acoustic_penalty) || (options.strict && p.duration_penalty>=180.)) continue;
          auto add=[&](bool leading) {
            PlannedUnit u{UnitKind::Phoneme,tokens[first_word],p.source_word,p.labels,p.clip_id,
              (length>=2 ? first_center : !leading) ? p.first_center : p.start_sample,
              (length>=2 ? last_center : leading) ? p.last_center : p.end_sample,
              static_cast<std::int64_t>(first_word),p.confidence};
            u.starts_at_phone_center=length>=2 ? first_center : !leading;
            u.ends_at_phone_center=length>=2 ? last_center : leading;
            if(length>2) u.center_run_phone_count=length;
            u.end_word_group=static_cast<std::int64_t>(last_word);
            u.target_text=JoinTokens(std::vector<std::string>(tokens.begin()+first_word,tokens.begin()+last_word+1));
            u.pause_before_ms=!u.starts_at_phone_center && i==starts[first_word] ? pauses[first_word] : 0;
            double discarded=0.,duration=0.,quality=0.,stress=0.,expected_ms=0.;
            for(std::size_t n=0;n<length;++n) {
              const double fraction=length==1?.5:((n==0?first_center:(n+1==length?last_center:false))?.5:1.);
              discarded+=fraction*(recorded_word[word_at[i+n]]?35.:0.);
              if(length<=2) {duration+=fraction*p.center_duration[n];quality+=fraction*p.center_quality[n];}
              const auto &wanted=stressed_target[i+n];
              if((wanted.back()=='1' || wanted.back()=='2') && p.stressed_labels[n].back()=='0') stress+=fraction*90.;
              const bool vowel=std::string(" AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW ").find(" "+target[i+n]+" ")!=std::string::npos;
              expected_ms+=fraction*(vowel?(wanted.back()=='1'?180.:140.):70.);
            }
            if(length>2) {
              duration=p.duration_penalty-(first_center?p.center_duration[0]*.5:0.)-(last_center?p.center_duration[1]*.5:0.);
              quality=p.acoustic_penalty-(first_center?p.center_quality[0]*.5:0.)-(last_center?p.center_quality[1]*.5:0.);
            }
            const double ms=1000.*(u.end_sample-u.start_sample)/impl_->sample_rate;
            // These are half-phone spans. Long emphatic vowels must not gain
            // an advantage just because a source transition exists.
            const double timing=std::max(0.,ms-expected_ms*1.7)*.8;
            const double boundaries=(!u.starts_at_phone_center && i==starts[first_word] && !p.begins_word?50.:0.)+
              (!u.ends_at_phone_center && last+1==ends[last_word] && !p.ends_word?180.:0.);
            const auto start=i*2+(u.starts_at_phone_center?1:0);
            const auto end=length>=2?last*2+(last_center?1:2):i*2+(leading?1:2);
            if(u.end_sample>u.start_sample)
              edges[start].push_back({end,std::move(u),25.+duration+quality+stress+timing+discarded+boundaries+band_cost(p.pitch)+100.*(last_word-first_word)});
          };
          add(true);if(length==1)add(false);
        }
      }
    }
  }
  const auto &wave = impl_->ensure_master_wave();
  // The beam compares the same boundary against many predecessor states.
  // Its acoustic window depends only on this source position, not the path.
  std::unordered_map<std::int64_t,FeatureFrame> boundary_features;
  auto feature = [&](std::int64_t sample) {
    if(const auto found=boundary_features.find(sample);found!=boundary_features.end())
      return found->second;
    FeatureFrame f;
    if (!impl_->features.empty()) {
      const auto centre=std::min<std::size_t>(impl_->features.size()-1,
          static_cast<std::size_t>(std::max<std::int64_t>(0,sample))/impl_->feature_hop);
      std::vector<float> pitches;
      const auto radius=std::max<std::size_t>(1,wave.sample_rate/100/impl_->feature_hop);
      const auto first=centre>radius?centre-radius:0,last=std::min(impl_->features.size(),centre+radius+1);
      for(auto i=first;i<last;++i) {
        const auto &row=impl_->features[i];
        f.rms+=row.rms;
        for(std::size_t j=0;j<8;++j) f.spectrum[j]+=row.spectrum[j];
        if(row.pitch>0 && row.voicing>=.8 && row.rms>.003) pitches.push_back(row.pitch);
      }
      f.rms/=last-first;for(auto &v:f.spectrum) v/=last-first;
      if(pitches.size()>=3 && pitches.size()*4>=(last-first)*3) {
        std::sort(pitches.begin(),pitches.end());
        if(12.*std::log2(pitches.back()/pitches.front())<=4.) {
          f.pitch=pitches[pitches.size()/2];f.voicing=1.;
        }
      }
      boundary_features.emplace(sample,f);
      return f;
    }
    auto p = impl_->profile_for_range(
        std::max<std::int64_t>(0, sample - wave.sample_rate / 50),
        std::min<std::int64_t>(static_cast<std::int64_t>(wave.samples.size()),
                               sample + wave.sample_rate / 50));
    f.pitch = static_cast<float>(p.pitch_hz.value_or(0));
    f.rms = static_cast<float>(p.rms);
    f.voicing = f.pitch > 0 ? 1.f : 0.f;
    boundary_features.emplace(sample,f);
    return f;
  };
  auto join_cost = [&](const PlannedUnit &a, const PlannedUnit &b) {
    if (a.clip_id == b.clip_id && a.end_sample == b.start_sample)
      return 0.;
    const auto left = feature(
        std::max(a.start_sample, a.end_sample - wave.sample_rate / 100));
    const auto right = feature(
        std::min(b.end_sample - 1, b.start_sample + wave.sample_rate / 100));
    double cost = a.ends_at_phone_center && b.starts_at_phone_center &&
        !a.phones.empty() && !b.phones.empty() && a.phones.back()==b.phones.front() ? center_join_cost : 100.;
    if (left.pitch > 0 && right.pitch > 0 && left.voicing > .65 &&
        right.voicing > .65) {
      const double st = std::abs(12. * std::log2(right.pitch / left.pitch));
      // Pitch is a tie-breaker, not a reason to discard a longer intact run.
      cost += std::min(36.,st * 3.);
    }
    if (left.rms > .001 && right.rms > .001)
      cost += std::min<double>(
                  30., std::abs(20 * std::log10(right.rms / left.rms))) *
              .5;
    for (std::size_t j = 0; j < 8; ++j)
      cost += std::abs(left.spectrum[j] - right.spectrum[j]) * .5;
    if ((left.voicing > .65) != (right.voicing > .65))
      cost += 2.;
    return cost;
  };
  // Paths share their immutable prefixes. Copying every selected unit into
  // every candidate becomes expensive on paragraphs and wider beams.
  struct Path {
    const PlannedUnit *unit;
    std::shared_ptr<const Path> previous;
  };
  struct State {
    double cost{};
    std::shared_ptr<const Path> path;
  };
  std::vector<std::vector<State>> dp(edges.size() + 1);
  dp[0].push_back({});
  const std::size_t beam = std::clamp<std::size_t>(options.beam_width, 1, 128);
  auto trim = [&](auto &states) {
    std::stable_sort(
        states.begin(), states.end(),
        [](const auto &a, const auto &b) { return a.cost < b.cost; });
    if (states.size() > beam)
      states.resize(beam);
  };
  for (std::size_t i = 0; i < edges.size(); ++i) {
    if (options.stop_token.stop_requested())
      throw std::runtime_error("Synthesis cancelled");
    trim(dp[i]);
    // Per-ending beam retains previous occurrence identity so join costs remain
    // pairwise.
    for (const auto &edge : edges[i]) {
      const State *best = nullptr;
      double best_cost = std::numeric_limits<double>::infinity();
      for (const auto &state : dp[i]) {
        double cost = state.cost + edge.penalty +
                      (1. - edge.unit.confidence.value_or(.5));
        if (state.path)
          cost += join_cost(*state.path->unit, edge.unit);
        if (cost < best_cost) {
          best_cost = cost;
          best = &state;
        }
      }
      if (best) {
        State next{best_cost,std::make_shared<Path>(Path{&edge.unit,best->path})};
        auto &dest = dp[edge.end];
        dest.push_back(std::move(next));
        if (dest.size() > beam * 4)
          trim(dest);
      }
    }
    if (i > 0)
      dp[i].clear();
  }
  auto &completed = dp.back();
  if (completed.empty())
    throw std::runtime_error(
        "No acceptable sound coverage: phonemes are missing or their durations "
        "were rejected. Rebuild/inspect the pack or try best-effort mode");
  trim(completed);
  auto best = std::move(completed.front());
  std::vector<PlannedUnit> selected;
  for(auto path=best.path;path;path=path->previous) selected.push_back(*path->unit);
  std::reverse(selected.begin(),selected.end());
  bool phone_splicing =
      std::any_of(selected.begin(), selected.end(),
                  [](const auto &u) { return u.kind == UnitKind::Phoneme; });
  if (phone_splicing &&
      impl_->report.find("legacy-import") != std::string::npos)
    warnings.push_back(
        "This pack uses legacy imported alignments. Rebuild it from "
        "recordings; strict coverage cannot repair wrong timestamps.");
  if (std::count_if(selected.begin(), selected.end(), [](const auto &u) {
        return u.kind == UnitKind::Phoneme;
      }) > 1)
    warnings.push_back("Some words are assembled from recorded sound pieces; "
                       "inspect and audition their cuts.");
  // Preserve original contiguous source audio as one run, including within new
  // words.
  std::vector<PlannedUnit> merged;
  for (auto &u : selected) {
    if (u.approximated)
      warnings.push_back("Approximate phone in: " + u.target_text);
    if (!merged.empty() && u.pause_before_ms == 0 &&
        merged.back().clip_id == u.clip_id &&
        merged.back().end_sample == u.start_sample) {
      auto &back = merged.back();
      back.end_sample = u.end_sample;
      back.end_word_group=u.end_word_group;
      const auto shared=back.ends_at_phone_center && u.starts_at_phone_center &&
          !back.phones.empty() && !u.phones.empty() && back.phones.back()==u.phones.front();
      back.phones.insert(back.phones.end(), u.phones.begin()+(shared?1:0), u.phones.end());
      back.ends_at_phone_center=u.ends_at_phone_center;
      back.center_run_phone_count=std::max(back.center_run_phone_count,u.center_run_phone_count);
      back.approximated = back.approximated || u.approximated;
      if (back.target_text != u.target_text)
        back.target_text += ' ' + u.target_text;
    } else
      merged.push_back(std::move(u));
  }
  PlanResult result{impl_->merc,        std::string(text),
                    JoinTokens(tokens), impl_->master_audio_path,
                    impl_->sample_rate, std::move(merged)};
  result.warnings = std::move(warnings);
  result.score = best.cost;
  return result;
}
