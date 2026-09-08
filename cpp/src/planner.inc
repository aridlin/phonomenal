PlanResult VoiceBank::PlanText(std::string_view text, const SynthesizeOptions& options) const {
    std::lock_guard guard(impl_->mutex);
    if(text.size()>16384)throw std::runtime_error("Prompt exceeds 16384 UTF-8 bytes; split into sentences");
    const auto tokens=NormalizeTokens(text);
    if(tokens.empty()||tokens.size()>512)throw std::runtime_error("Expected 1 to 512 spoken words");
    std::vector<std::string> target;
    std::vector<std::size_t> starts,ends,word_at;
    std::vector<std::string> warnings;
    for(std::size_t w=0;w<tokens.size();++w) {
        starts.push_back(target.size());std::vector<std::string> pronunciation;
        auto it=impl_->pronunciation_index.find(tokens[w]);
        if(it!=impl_->pronunciation_index.end())pronunciation=it->second;
        else {
            pronunciation=NativePronunciation(tokens[w]);
            if(pronunciation.empty()) {
                if(options.strict)throw std::runtime_error("No pronunciation for '"+tokens[w]+"'; install eSpeak NG or provide a lexicon/phones");
                pronunciation=GuessPronunciation(tokens[w]);warnings.push_back("Heuristic pronunciation: "+tokens[w]);
            }
        }
        if(pronunciation.empty())throw std::runtime_error("Cannot pronounce '"+tokens[w]+"'");
        for(const auto& phone:pronunciation){target.push_back(NormalizePhoneLabel(phone));word_at.push_back(w);}
        ends.push_back(target.size());
    }
    if(target.size()>4096)throw std::runtime_error("Prompt exceeds phone limit");
    struct Edge {std::size_t end;PlannedUnit unit;double penalty{};};
    std::vector<std::vector<Edge>> edges(target.size());
    // Match source token runs on demand: no hard four/eight-word phrase ceiling and no quadratic phrase index.
    for(std::size_t w=0;w<tokens.size();++w) {
        for(const auto& record:impl_->records) {
            for(std::size_t rs=0;rs<record.words.size();++rs) {
                if(record.words[rs].text!=tokens[w])continue;
                for(std::size_t n=0;w+n<tokens.size()&&rs+n<record.words.size()&&n<static_cast<std::size_t>(std::max<std::int64_t>(1,options.max_chunk_words));++n) {
                    if(record.words[rs+n].text!=tokens[w+n])break;
                    const auto& first=record.words[rs];const auto& last=record.words[rs+n];
                    PlannedUnit u{n?UnitKind::ExactChunk:UnitKind::ExactWord,JoinTokens(std::vector<std::string>(tokens.begin()+static_cast<std::ptrdiff_t>(w),tokens.begin()+static_cast<std::ptrdiff_t>(w+n+1))),"",{},record.clip_id,first.start_sample,last.end_sample,static_cast<std::int64_t>(w),last.confidence};
                    u.text=u.target_text;edges[starts[w]].push_back({ends[w+n],std::move(u),0.});
                }
            }
        }
    }
    for(std::size_t i=0;i<target.size();++i) {
        const auto max_len=std::min<std::size_t>(static_cast<std::size_t>(std::max<std::int64_t>(1,options.max_phone_ngram)),target.size()-i);
        for(std::size_t len=1;len<=max_len;++len) {
            const auto key=MakeKey(std::span<const std::string>(target.data()+i,len));
            auto found=impl_->phone_index.find(key);bool approximated=false;
            if(found==impl_->phone_index.end()&&len==1&&!options.strict) {
                for(const auto& alt:PhoneAlternatives(target[i])) {auto candidate=impl_->phone_index.find(alt);if(candidate!=impl_->phone_index.end()){found=candidate;approximated=true;break;}}
            }
            if(found==impl_->phone_index.end())continue;
            for(const auto& p:found->second) {
                PlannedUnit u{UnitKind::Phoneme,tokens[word_at[i]],p.source_word,p.labels,p.clip_id,p.start_sample,p.end_sample,static_cast<std::int64_t>(word_at[i]),p.confidence};
                u.approximated=approximated;
                edges[i].push_back({i+len,std::move(u),.15*static_cast<double>(len)+(approximated?1000000.:0.)});
            }
        }
    }
    const auto& wave=impl_->ensure_master_wave();
    auto feature=[&](std::int64_t sample) {
        FeatureFrame f;
        if(!impl_->features.empty())return impl_->features[std::min<std::size_t>(impl_->features.size()-1,static_cast<std::size_t>(std::max<std::int64_t>(0,sample))/impl_->feature_hop)];
        auto p=impl_->profile_for_range(std::max<std::int64_t>(0,sample-wave.sample_rate/50),std::min<std::int64_t>(static_cast<std::int64_t>(wave.samples.size()),sample+wave.sample_rate/50));
        f.pitch=static_cast<float>(p.pitch_hz.value_or(0));f.rms=static_cast<float>(p.rms);f.voicing=f.pitch>0?1.f:0.f;return f;
    };
    auto join_cost=[&](const PlannedUnit& a,const PlannedUnit& b) {
        if(a.clip_id==b.clip_id&&a.end_sample==b.start_sample)return 0.;
        const auto left=feature(std::max(a.start_sample,a.end_sample-wave.sample_rate/100));
        const auto right=feature(std::min(b.end_sample-1,b.start_sample+wave.sample_rate/100));
        double cost=100.;
        if(left.pitch>0&&right.pitch>0&&left.voicing>.65&&right.voicing>.65) {
            const double st=std::abs(12.*std::log2(right.pitch/left.pitch));cost+=st*3.;if(st>8)cost+=150.;
        }
        if(left.rms>.001&&right.rms>.001)cost+=std::min<double>(30.,std::abs(20*std::log10(right.rms/left.rms)))*.5;
        for(std::size_t j=0;j<8;++j)cost+=std::abs(left.spectrum[j]-right.spectrum[j])*.5;
        if((left.voicing>.65)!=(right.voicing>.65))cost+=2.;
        return cost;
    };
    struct State {double cost{};std::vector<PlannedUnit> units;};
    std::vector<std::vector<State>> dp(target.size()+1);dp[0].push_back({});
    const std::size_t beam=std::clamp<std::size_t>(options.beam_width,1,128);
    auto trim=[&](auto& states){std::stable_sort(states.begin(),states.end(),[](const auto&a,const auto&b){return a.cost<b.cost;});if(states.size()>beam)states.resize(beam);};
    for(std::size_t i=0;i<target.size();++i) {
        if(options.stop_token.stop_requested())throw std::runtime_error("Synthesis cancelled");
        trim(dp[i]);
        // Per-ending beam retains previous occurrence identity so join costs remain pairwise.
        for(const auto& edge:edges[i]) {
            const State* best=nullptr;double best_cost=std::numeric_limits<double>::infinity();
            for(const auto& state:dp[i]) {
                double cost=state.cost+edge.penalty+(1.-edge.unit.confidence.value_or(.5));
                if(!state.units.empty())cost+=join_cost(state.units.back(),edge.unit);
                if(cost<best_cost){best_cost=cost;best=&state;}
            }
            if(best) {auto next=*best;next.cost=best_cost;next.units.push_back(edge.unit);auto& dest=dp[edge.end];dest.push_back(std::move(next));if(dest.size()>beam*4)trim(dest);}
        }
        if(i>0)dp[i].clear();
    }
    auto& completed=dp.back();
    if(completed.empty())throw std::runtime_error("Missing sound coverage for prompt; inspect pack inventory or try --phones / best-effort mode");
    trim(completed);auto best=std::move(completed.front());
    // Preserve original contiguous source audio as one run, including within new words.
    std::vector<PlannedUnit> merged;
    for(auto& u:best.units) {
        if(u.approximated)warnings.push_back("Approximate phone in: "+u.target_text);
        if(!merged.empty()&&merged.back().clip_id==u.clip_id&&merged.back().end_sample==u.start_sample) {
            auto& back=merged.back();back.end_sample=u.end_sample;back.phones.insert(back.phones.end(),u.phones.begin(),u.phones.end());back.approximated=back.approximated||u.approximated;
            if(back.target_text!=u.target_text)back.target_text+=' '+u.target_text;
        }else merged.push_back(std::move(u));
    }
    // Punctuation pauses are mapped to token boundaries; source-internal pauses stay intact.
    std::vector<int> pauses(tokens.size());std::size_t token_cursor=0;std::string rawword;
    for(char ch:std::string(text)+" ") {
        if(std::isalpha(static_cast<unsigned char>(ch))||ch=='\'')rawword+=ch;
        else {if(!rawword.empty()){++token_cursor;rawword.clear();}if(token_cursor<pauses.size()){if(ch=='.'||ch=='!'||ch=='?')pauses[token_cursor]=180;else if(ch==','||ch==';'||ch==':')pauses[token_cursor]=90;}}
    }
    for(auto& u:merged)if(u.word_group>=0&&static_cast<std::size_t>(u.word_group)<pauses.size())u.pause_before_ms=pauses[static_cast<std::size_t>(u.word_group)];
    PlanResult result{impl_->merc,std::string(text),JoinTokens(tokens),impl_->master_audio_path,impl_->sample_rate,std::move(merged)};
    result.warnings=std::move(warnings);result.score=best.cost;return result;
}
