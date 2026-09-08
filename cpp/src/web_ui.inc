// Browser-specific I/O around the same FT widgets and native engine.
static bool web_mode() { return ft::active_mode() == ft::Mode::Web; }
static std::string web_escape(std::string_view text) {
  std::string out;
  for (char c : text) {
    if (c == '&')
      out += "&amp;";
    else if (c == '<')
      out += "&lt;";
    else if (c == '>')
      out += "&gt;";
    else if (c == '"')
      out += "&quot;";
    else if (c == '\'')
      out += "&#39;";
    else
      out += c;
  }
  return out;
}
static std::string unique_web_name(const std::string &suffix) {
  return std::to_string(
             std::chrono::system_clock::now().time_since_epoch().count()) +
         suffix;
}
static std::vector<std::uint8_t> decode_upload(std::string_view encoded) {
  if (encoded.empty() || encoded.size() > 88 * 1024 * 1024 ||
      encoded.size() % 4)
    throw std::runtime_error(
        "Upload must be a base64-encoded file under 64 MiB");
  constexpr std::string_view alphabet =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::vector<std::uint8_t> result;
  result.reserve(encoded.size() / 4 * 3);
  for (std::size_t i = 0; i < encoded.size(); i += 4) {
    std::uint32_t value = 0;
    int padding = 0;
    for (int n = 0; n < 4; ++n) {
      char ch = encoded[i + n];
      if (ch == '=') {
        if (i + 4 != encoded.size() || n < 2)
          throw std::runtime_error("Invalid upload encoding");
        ++padding;
        value <<= 6;
      } else {
        auto digit = alphabet.find(ch);
        if (padding || digit == std::string_view::npos)
          throw std::runtime_error("Invalid upload encoding");
        value = (value << 6) | static_cast<std::uint32_t>(digit);
      }
    }
    result.push_back(static_cast<std::uint8_t>(value >> 16));
    if (padding < 2)
      result.push_back(static_cast<std::uint8_t>(value >> 8));
    if (!padding)
      result.push_back(static_cast<std::uint8_t>(value));
  }
  if (result.size() > 64 * 1024 * 1024)
    throw std::runtime_error("Upload exceeds 64 MiB");
  return result;
}
static void web_upload(App &a) {
  const char *data = ft::param("voice_upload");
  if (!ft::is_post() || !data)
    return;
  std::string encoded = data;
  if (encoded.empty())
    return;
  if (a.busy) {
    ft::set_status(409, "Busy");
    throw std::runtime_error("Wait for the current job before uploading");
  }
  const char *filename = ft::param("voice_filename");
  std::string name = filename ? filename : "";
  if (name.empty() || name.size() > 160 ||
      name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVW"
                             "XYZ0123456789._-") != std::string::npos ||
      name.front() == '.')
    throw std::runtime_error("Invalid upload filename");
  auto extension = fs::path(name).extension().string();
  std::transform(
      extension.begin(), extension.end(), extension.begin(),
      [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  const bool pack = extension == ".vcpack";
  const std::vector<std::string> allowed{".mp3", ".wav",  ".ogg", ".flac",
                                         ".m4a", ".webm", ".txt"};
  if (!pack &&
      std::find(allowed.begin(), allowed.end(), extension) == allowed.end())
    throw std::runtime_error(
        "Choose a voice pack, speech audio, or matching .txt transcript");
  std::string take = ft::param("voice_take") ? ft::param("voice_take") : "";
  if (!take.empty() &&
      (take.find_first_not_of("0123456789") != std::string::npos ||
       take.size() > 3 || std::stoul(take) >= kReadingScript.size()))
    throw std::runtime_error("Invalid recording take");
  auto bytes = decode_upload(encoded);
  if (extension == ".txt" && bytes.size() > 128 * 1024)
    throw std::runtime_error("Transcript is too long");
  if (!pack && a.preset != 9) {
    copy(a.source, utf8(a.root / "recordings" / unique_web_name("-voice")));
    copy(a.output, utf8(a.root / "data/packages" / unique_web_name(".vcpack")));
  }
  auto folder = pack ? a.root / "data/packages" : path_utf8(a.source);
  fs::create_directories(folder);
  auto target = folder / name;
  if (fs::exists(target))
    throw std::runtime_error("That filename already exists. Rename the upload "
                             "to preserve the existing file.");
  auto temporary = folder / unique_web_name(".upload");
  {
    std::ofstream file(temporary, std::ios::binary);
    file.write(reinterpret_cast<const char *>(bytes.data()), bytes.size());
    if (!file)
      throw std::runtime_error("Could not save upload");
  }
  try {
    if (pack) {
      auto validating = temporary;
      validating.replace_extension(".vcpack");
      fs::rename(temporary, validating);
      temporary = validating;
      auto checked = phonomenal_splicer::VoiceBank::Load(temporary);
    }
    fs::rename(temporary, target);
  } catch (...) {
    std::error_code ec;
    fs::remove(temporary, ec);
    throw;
  }
  if (pack) {
    choose_pack(a, target);
    a.page = 1;
  } else {
    a.preset = 9;
    copy(a.voice, "my-voice");
    copy(a.source, utf8(folder));
    a.page = 0;
    if (!take.empty()) {
      auto index = std::stoul(take);
      if (index >= kReadingScript.size())
        throw std::runtime_error("Invalid recording take");
      auto transcript = target;
      transcript.replace_extension(".txt");
      std::ofstream file(transcript);
      file << kReadingScript[index] << '\n';
      if (!file)
        throw std::runtime_error("Could not save take transcript");
      a.take = std::min(static_cast<int>(kReadingScript.size()) - 1,
                        static_cast<int>(index) + 1);
    }
  }
  a.message("Imported " + name);
}
static void web_upload_control() {
  ft::html(
      R"HTML(<section><label>Import voice pack or speech files (up to 64 MiB each)<input type="file" multiple accept=".vcpack,.mp3,.wav,.ogg,.flac,.m4a,.webm,.txt" onchange="phonomenalUploadFiles(this.files)"></label><small id="voice-upload-status"></small></section>)HTML");
}
static void web_recorder(App &a) {
  std::string html =
      "<section><button type=\"button\" data-take=\"" + std::to_string(a.take) +
      "\" onclick=\"phonomenalRecord(this)\">Record this take in "
      "browser</button><small id=\"voice-recorder-status\"></small></section>";
  ft::html(html.c_str());
}
static const char *web_head = R"HTML(<style>
:root{color-scheme:dark;--desk:#1d2021;--paper:#282828;--paper2:#32302f;--ink:#ebdbb2;--muted:#bdae93;--faint:#a89984;--border:#665c54;--button:#3c3836;--hover:#504945;--active:#665c54;--input:#1d2021;--accent:#d79921;--warning:#fabd2f;--success:#b8bb26}
a{color:#83a598}a:hover{color:#8ec07c}h1{color:#fabd2f}audio{width:100%;margin:12px 0}section{max-width:100%}small{display:block;margin:6px 0;color:var(--muted)}
@media(max-width:600px){main{margin:8px;padding:12px}h1{font-size:23px}input[type=file]{font-size:12px}}
</style><script>
window.phonomenalSend = async function(file,take) {
 if(file.size>64*1024*1024) throw new Error('File exceeds 64 MiB');
 const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=reject;r.readAsDataURL(file)});
 const name=file.name.replace(/[^a-zA-Z0-9._-]/g,'_').replace(/^\./,'_');
 const body=new URLSearchParams({voice_upload:data,voice_filename:name});
 if(take!==undefined)body.set('voice_take',String(take));
 const response=await fetch(location.pathname,{method:'POST',body});
 if(!response.ok) throw new Error('Upload rejected ('+response.status+'). Check filename, size, or active job.');
};
window.phonomenalUploadFiles=async function(files){
 const status=document.getElementById('voice-upload-status');
 try {for(const f of files){status.textContent='Uploading '+f.name;await phonomenalSend(f);}location.reload();}
 catch(e){status.textContent=e.message;}
};
window.phonomenalRecord=async function(button){
 const status=document.getElementById('voice-recorder-status');
 if(window.phonomenalRecorder?.state==='recording'){window.phonomenalRecorder.stop();return;}
 try {
  const stream=await navigator.mediaDevices.getUserMedia({audio:true});
  const type=['audio/webm;codecs=opus','audio/ogg;codecs=opus','audio/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
  const recorder=new MediaRecorder(stream,type?{mimeType:type}:{});window.phonomenalRecorder=recorder;
  const chunks=[],take=Number(button.dataset.take);
  recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
  const timer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop()},180000);
  recorder.onstop=async()=>{clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());button.textContent='Uploading take...';
   try{const ext=recorder.mimeType.includes('ogg')?'ogg':recorder.mimeType.includes('mp4')?'m4a':'webm';const file=new File(chunks,'take_'+String(take+1).padStart(3,'0')+'_'+Date.now()+'.'+ext,{type:recorder.mimeType});await phonomenalSend(file,take);location.reload()}
   catch(e){status.textContent=e.message;button.textContent='Record this take in browser'}
  };
  recorder.start();button.textContent='Stop and save this take';status.textContent='Recording your browser microphone (maximum 180 seconds).';
 }catch(e){status.textContent=e.message;}
};
</script>)HTML";
