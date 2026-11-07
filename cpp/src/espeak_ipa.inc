// UTF-8 byte literals keep embedded Windows builds independent of code page.
// eSpeak's IPA output avoids language-table-dependent ASCII vowel names.
// Stress/length are parsed separately; an unknown phone rejects the result,
// so unsupported pronunciations keep the existing explicit fallback warning.
std::vector<std::string> ParseEspeakIpa(std::string_view raw) {
  static const std::unordered_map<std::string,std::vector<std::string>> phones={
    {"p",{"P"}},{"b",{"B"}},{"t",{"T"}},{"d",{"D"}},{"k",{"K"}},{"g",{"G"}},{"\xc9\xa1",{"G"}},
    {"f",{"F"}},{"v",{"V"}},{"\xce\xb8",{"TH"}},{"\xc3\xb0",{"DH"}},{"s",{"S"}},{"z",{"Z"}},
    {"\xca\x83",{"SH"}},{"\xca\x92",{"ZH"}},{"h",{"HH"}},{"\x74\xca\x83",{"CH"}},{"\x64\xca\x92",{"JH"}},
    {"\x74\xcd\xa1\xca\x83",{"CH"}},{"\x64\xcd\xa1\xca\x92",{"JH"}},{"m",{"M"}},{"n",{"N"}},{"\xc5\x8b",{"NG"}},
    {"l",{"L"}},{"\xc9\xab",{"L"}},{"r",{"R"}},{"\xc9\xb9",{"R"}},{"\xc9\xbe",{"T"}},
    {"w",{"W"}},{"\xca\x8d",{"HH","W"}},{"j",{"Y"}},
    {"i",{"IY"}},{"\xc9\xaa",{"IH"}},{"\xe1\xb5\xbb",{"IH"}},{"\xc9\xa8",{"IH"}},
    {"\xc9\x9b",{"EH"}},{"\xc3\xa6",{"AE"}},{"a",{"AA"}},{"\xc9\x91",{"AA"}},{"\xc9\x92",{"AA"}},
    {"\xc9\x94",{"AO"}},{"\xca\x8a",{"UH"}},{"u",{"UW"}},{"\xca\x8c",{"AH"}},{"\xc9\x99",{"AH"}},{"\xc9\x90",{"AH"}},
    {"\xc9\x9c",{"ER"}},{"\xc9\x9a",{"ER"}},{"\xc9\x9d",{"ER"}},
    {"\x65\xc9\xaa",{"EY"}},{"\x61\xc9\xaa",{"AY"}},{"\xc9\x91\xc9\xaa",{"AY"}},{"\x61\xca\x8a",{"AW"}},{"\xc9\x91\xca\x8a",{"AW"}},
    {"\xc9\x94\xc9\xaa",{"OY"}},{"\x6f\xca\x8a",{"OW"}},{"\xc9\x99\xca\x8a",{"OW"}},{"e",{"EY"}},{"o",{"OW"}},
    {"\xc9\x99\x6c",{"AH","L"}},{"\xc9\x99\x6e",{"AH","N"}},{"\xc9\x99\x6d",{"AH","M"}},
    {"\xc9\x99\xc9\xb9",{"ER"}},{"\xc9\x99\x72",{"ER"}},{"\xc9\xb9\xcc\xa9",{"ER"}},{"\x72\xcc\xa9",{"ER"}},
    {"\x6c\xcc\xa9",{"AH","L"}},{"\x6d\xcc\xa9",{"AH","M"}},{"\x6e\xcc\xa9",{"AH","N"}},{"\xc5\x8b\xcc\xa9",{"AH","NG"}},
    {"\x69\xc9\x99",{"IY","AH"}},{"\xc9\xaa\xc9\x99",{"IH","AH"}},{"\xca\x8a\xc9\x99",{"UH","AH"}},
    {"\xc9\x9b\xc9\x99",{"EH","AH"}},{"\x65\xc9\x99",{"EH","AH"}},{"\x61\xc9\xaa\xc9\x99",{"AY","AH"}},
    {"\x61\xca\x8a\xc9\x99",{"AW","AH"}},{"\x61\xc9\xaa\xc9\x9a",{"AY","ER"}}
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
        label.push_back(stress);stress='0';
      }
      out.push_back(std::move(label));
    }
    token.clear();
  };
  for(std::size_t i=0;i<raw.size();) {
    const auto remaining=raw.substr(i);
    if(remaining.starts_with("\xcb\x88")) {stress='1';i+=std::string_view("\xcb\x88").size();continue;}
    if(remaining.starts_with("\xcb\x8c")) {stress='2';i+=std::string_view("\xcb\x8c").size();continue;}
    if(remaining.starts_with("\xcb\x90")) {i+=std::string_view("\xcb\x90").size();continue;}
    if(remaining.starts_with("\xcb\x91")) {i+=std::string_view("\xcb\x91").size();continue;}
    const auto c=static_cast<unsigned char>(raw[i++]);
    if(c=='|' || std::isspace(c)) flush();else token.push_back(static_cast<char>(c));
  }
  flush();
  return valid?out:std::vector<std::string>{};
}
