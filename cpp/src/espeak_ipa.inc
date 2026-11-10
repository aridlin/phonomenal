// eSpeak's IPA output avoids language-table-dependent ASCII vowel names.
// Stress/length are parsed separately; an unknown phone rejects the result,
// so unsupported pronunciations keep the existing explicit fallback warning.
std::vector<std::string> ParseEspeakIpa(std::string_view raw) {
  static const std::unordered_map<std::string,std::vector<std::string>> phones={
    {"p",{"P"}},{"b",{"B"}},{"t",{"T"}},{"d",{"D"}},{"k",{"K"}},{"g",{"G"}},{"ɡ",{"G"}},
    {"f",{"F"}},{"v",{"V"}},{"θ",{"TH"}},{"ð",{"DH"}},{"s",{"S"}},{"z",{"Z"}},
    {"ʃ",{"SH"}},{"ʒ",{"ZH"}},{"h",{"HH"}},{"tʃ",{"CH"}},{"dʒ",{"JH"}},
    {"t͡ʃ",{"CH"}},{"d͡ʒ",{"JH"}},{"m",{"M"}},{"n",{"N"}},{"ŋ",{"NG"}},
    {"l",{"L"}},{"ɫ",{"L"}},{"r",{"R"}},{"ɹ",{"R"}},{"ɾ",{"T"}},
    {"w",{"W"}},{"ʍ",{"HH","W"}},{"j",{"Y"}},
    {"i",{"IY"}},{"ɪ",{"IH"}},{"ᵻ",{"IH"}},{"ɨ",{"IH"}},
    {"ɛ",{"EH"}},{"æ",{"AE"}},{"a",{"AA"}},{"ɑ",{"AA"}},{"ɒ",{"AA"}},
    {"ɔ",{"AO"}},{"ʊ",{"UH"}},{"u",{"UW"}},{"ʌ",{"AH"}},{"ə",{"AH"}},{"ɐ",{"AH"}},
    {"ɜ",{"ER"}},{"ɚ",{"ER"}},{"ɝ",{"ER"}},
    {"eɪ",{"EY"}},{"aɪ",{"AY"}},{"ɑɪ",{"AY"}},{"aʊ",{"AW"}},{"ɑʊ",{"AW"}},
    {"ɔɪ",{"OY"}},{"oʊ",{"OW"}},{"əʊ",{"OW"}},{"e",{"EY"}},{"o",{"OW"}},
    {"əl",{"AH","L"}},{"ən",{"AH","N"}},{"əm",{"AH","M"}},
    {"əɹ",{"ER"}},{"ər",{"ER"}},{"ɹ̩",{"ER"}},{"r̩",{"ER"}},
    {"l̩",{"AH","L"}},{"m̩",{"AH","M"}},{"n̩",{"AH","N"}},{"ŋ̩",{"AH","NG"}},
    {"iə",{"IY","AH"}},{"ɪə",{"IH","AH"}},{"ʊə",{"UH","AH"}},
    {"ɛə",{"EH","AH"}},{"eə",{"EH","AH"}},{"aɪə",{"AY","AH"}},
    {"aʊə",{"AW","AH"}},{"aɪɚ",{"AY","ER"}}
  };
  std::vector<std::string> out;
  std::string token;
  char stress='0';bool valid=true;
  auto flush=[&] {
    if(token.empty()) return;
    const auto found=phones.find(token);
    if(found==phones.end()) {valid=false;token.clear();return;}
    for(auto label:found->second) {
      if(std::string(" AA AE AH AO AW AY EH ER EY IH IY OW OY UH UW ").find(" "+label+" ")!=std::string::npos) {
        stress='0'; // private control: map phones without preserving stress
      }
      out.push_back(std::move(label));
    }
    token.clear();
  };
  for(std::size_t i=0;i<raw.size();) {
    const auto remaining=raw.substr(i);
    if(remaining.starts_with("ˈ")) {stress='1';i+=std::string_view("ˈ").size();continue;}
    if(remaining.starts_with("ˌ")) {stress='2';i+=std::string_view("ˌ").size();continue;}
    if(remaining.starts_with("ː")) {i+=std::string_view("ː").size();continue;}
    if(remaining.starts_with("ˑ")) {i+=std::string_view("ˑ").size();continue;}
    const auto c=static_cast<unsigned char>(raw[i++]);
    if(c=='|' || std::isspace(c)) flush();else token.push_back(static_cast<char>(c));
  }
  flush();
  return valid?out:std::vector<std::string>{};
}
