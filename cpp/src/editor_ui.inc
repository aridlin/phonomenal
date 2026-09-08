// FT controls shared by GUI, TUI and web. Project JSON retains sample precision.
static void editor_command(App &a, std::vector<std::string> arguments,
                           std::stop_token stop = {}) {
  std::vector<std::string> command{a.python, utf8(a.root / "scripts/pack_editor.py")};
  command.insert(command.end(), arguments.begin(), arguments.end());
  if (RunChild(command, a.root, a.log, stop) != 0)
    throw std::runtime_error("Editor operation failed: " + read_tail(a.log));
}
static void editor_load(App &a) {
  const auto path = a.editor_project / a.editor_files.at(a.editor_selected);
  if (fs::file_size(path) >= a.editor_text.size())
    throw std::runtime_error("Section exceeds the 16 MiB text editor limit; use the project files with the CLI editor.");
  std::ifstream file(path, std::ios::binary);
  const std::string value{std::istreambuf_iterator<char>(file), {}};
  if (!file.eof() && file.fail()) throw std::runtime_error("Could not read editor section");
  std::copy(value.begin(), value.end(), a.editor_text.begin());
  a.editor_text[value.size()] = 0;
  a.editor_loaded = a.editor_selected; a.editor_dirty = false;
}
static void editor_draft(App &a) {
  const auto path = a.editor_project / a.editor_files.at(a.editor_loaded);
  const auto temporary = path.string() + ".tmp";
  { std::ofstream file(temporary, std::ios::binary); file << a.editor_text.data();
    if (!file) throw std::runtime_error("Could not save editor draft"); }
#ifdef _WIN32
  fs::remove(path);
#endif
  fs::rename(temporary, path); a.editor_dirty = false;
}
static void editor_index(App &a) {
  a.editor_files={"metadata.json","lexicon.json","extensions.json"};
  a.editor_labels={"Voice metadata","Pronunciation dictionary","Optional binary sections (base64)"};
  std::ifstream index(a.editor_project/"index.tsv");std::string line;
  while(std::getline(index,line)) {
    const auto tab=line.find('\t');if(tab==std::string::npos)continue;
    a.editor_files.push_back(line.substr(0,tab));a.editor_labels.push_back(line.substr(tab+1));
  }
}
static std::string editor_label(App &a) {
  return "Editable JSON: "+a.editor_files.at(a.editor_loaded)+"##"+utf8(a.editor_project.filename());
}
static void editor_ui(App &a) {
  // Consume the current FT text field before actions which switch documents.
  // This uses the vendored FT web widget ID algorithm, so a fast click cannot
  // discard edits still waiting for FT's input debounce.
  if(web_mode() && !a.editor_project.empty()) {
    const auto label=editor_label(a);std::uint32_t hash=2166136261u;
    for(unsigned char c:label){hash^=c;hash*=16777619u;}
    char id[32];std::snprintf(id,sizeof(id),"w_%08x",hash);
    if(const char *posted=ft::param(id);posted && std::strcmp(posted,a.editor_text.data())!=0) {
      const auto length=std::strlen(posted);
      if(length>=a.editor_text.size())throw std::runtime_error("Editor text exceeds 16 MiB");
      std::copy(posted,posted+length+1,a.editor_text.begin());a.editor_dirty=true;
    }
  }
  ft::text_wrapped("Edit recordings, transcripts, words, phonemes, confidence values, pronunciations, metadata and optional binary sections. Positions are absolute integer samples in master.wav; milliseconds = samples * 1000 / sample rate.");
  if (!a.pack_labels.empty()) {
    std::vector<const char *> labels; for (const auto &s:a.pack_labels) labels.push_back(s.c_str());
    int selected=a.selected_pack;
    if(ft::dropdown("Pack to edit",labels.data(),static_cast<int>(labels.size()),&selected) && !a.busy)
      choose_pack(a,a.pack_paths.at(selected));
  }
  if (!web_mode()) ft::input("Pack file to edit",a.pack,sizeof(a.pack));
  if(ft::button("Open a new editable copy") && !a.busy) {
    if(a.editor_dirty) throw std::runtime_error("Save the current draft before opening another pack.");
    const auto project=a.root/"data/editor"/unique_web_name("-project");
    editor_command(a,{"open","--pack",a.pack,"--project",utf8(project)});
    a.editor_project=project;
    editor_index(a);
    a.editor_selected=a.editor_files.size()>3?3:0;editor_load(a);
    a.editor_wave.clear();a.editor_svg.clear();
    {std::lock_guard lock(a.mutex);a.editor_download.clear();}
    a.message("Editable copy opened. Save draft edits, then validate and save a new pack.");
  }
  if(a.editor_project.empty())return;
  if(!web_mode()) ft::text_wrapped(("Project folder: "+utf8(a.editor_project)).c_str());
  if(web_mode())ft::html("<label>Replace master audio in this draft (mono PCM16 WAV, same sample rate)<input type=\"file\" accept=\".wav\" onchange=\"phonomenalReplaceMaster(this.files[0])\"></label>");
  else if(ft::button("Replace draft master WAV") && !a.busy) {
    const ft::FileFilter filters[]={{"PCM WAV","*.wav"}};
    const auto source=ft::open_file_dialog("Replacement master audio",filters,1);
    if(!source.empty()){editor_command(a,{"replace-audio","--project",utf8(a.editor_project),"--input",source});a.message("Master audio replaced in the draft. Review all affected boundaries.");}
  }
  ft::text_wrapped("Each recording JSON contains editable word and phone arrays. Add or remove entries, update their sample intervals, and keep each phone's zero-based word index correct. Save drafts before switching sections. Replacing master.wav or adding/removing recordings is also available through the project files and CLI.");
  std::vector<const char *> labels;for(const auto &s:a.editor_labels)labels.push_back(s.c_str());
  ft::dropdown("Section or recording",labels.data(),static_cast<int>(labels.size()),&a.editor_selected);
  if(ft::button("Load selected section") && !a.busy) {
    if(a.editor_dirty)throw std::runtime_error("Save the draft first to keep your edits.");
    editor_load(a);
    a.editor_start[0]=0;a.editor_end[0]=0;
  }
  if(ft::button("Save draft edits") && !a.busy) {editor_draft(a);a.message("Draft saved. The original voice pack has not been changed.");}
  for (bool remove : {false,true}) {
    if(ft::button(remove?"Delete this DRAFT recording":"Clone recording for a new sample selection") && !a.busy) {
      if(a.editor_loaded<3)throw std::runtime_error("Load a recording first.");
      editor_draft(a);
      const auto record=a.editor_files.at(a.editor_loaded).substr(7,6);
      editor_command(a,{remove?"delete-record":"clone-record","--project",utf8(a.editor_project),"--record",record});
      editor_index(a);a.editor_selected=remove?3:static_cast<int>(a.editor_files.size())-1;editor_load(a);
      a.message(remove?"Recording removed from the draft; original pack retained.":"Recording cloned. Edit its transcript, words, phones and audio sample selection.");
    }
  }
  const auto label=editor_label(a);
  if(ft::text_area(label.c_str(),a.editor_text.data(),static_cast<int>(a.editor_text.size()),20))a.editor_dirty=true;
  ft::input("Preview start sample (blank: recording start)",a.editor_start,sizeof(a.editor_start));
  ft::input("Preview end sample (blank: recording end)",a.editor_end,sizeof(a.editor_end));
  if(ft::button("Preview edited recording") && !a.busy) {
    if(a.editor_loaded<3)throw std::runtime_error("Load a recording section to preview it.");
    editor_draft(a);
    const auto name=unique_web_name(".wav");const auto path=a.root/"data/public"/name;
    std::vector<std::string> args{"preview","--project",utf8(a.editor_project),"--record",a.editor_files.at(a.editor_loaded).substr(7,6),"--output",utf8(path)};
    if(a.editor_start[0]){args.push_back("--start");args.push_back(a.editor_start);}
    if(a.editor_end[0]){args.push_back("--end");args.push_back(a.editor_end);}
    editor_command(a,args);
    if(web_mode()){a.editor_wave=a.web_files_url+name;auto svg=fs::path(name);svg.replace_extension(".svg");a.editor_svg=a.web_files_url+utf8(svg);}
    else {std::ifstream file(path,std::ios::binary);std::vector<std::uint8_t> bytes{std::istreambuf_iterator<char>(file),{}};a.audio.play(bytes);}
    a.message("Preview reflects the saved sample boundaries. Hover waveform labels for exact coordinates.");
  }
  if(web_mode() && !a.editor_wave.empty())ft::html(("<img alt=\"Waveform with word and phoneme boundaries\" style=\"width:100%\" src=\""+web_escape(a.editor_svg)+"\"><audio controls src=\""+web_escape(a.editor_wave)+"\"></audio>").c_str());
  if(ft::button("Validate and save NEW voice pack") && !a.busy) {
    editor_draft(a);const auto project=a.editor_project;
    const auto path=a.root/"data/packages"/unique_web_name("-edited.vcpack");
    const bool browser=web_mode(); const std::string python=a.python;
    a.message("Validating every interval, rebuilding acoustic features and saving a new pack...");
    a.task([&,project,path,browser,python](std::stop_token stop){
      const std::vector<std::string> command{python,utf8(a.root/"scripts/pack_editor.py"),"save","--project",utf8(project),"--output",utf8(path)};
      if(RunChild(command,a.root,a.log,stop)!=0)throw std::runtime_error("Pack save failed: "+read_tail(a.log));
      auto checked=phonomenal_splicer::VoiceBank::Load(path);
      std::string download;
      if(browser){fs::create_directories(a.root/"data/public");fs::copy_file(path,a.root/"data/public"/path.filename());download=a.web_files_url+utf8(path.filename());}
      {std::lock_guard lock(a.mutex);a.editor_download=download;}
      a.message("Validated new pack: "+utf8(path.filename())+". It is available in the player pack list.");
    });
  }
  web_region_begin("editor-results");
  {std::lock_guard lock(a.mutex);if(web_mode()&&!a.editor_download.empty())ft::html(("<p><a download href=\""+web_escape(a.editor_download)+"\">Download edited voice pack</a></p>").c_str());}
  web_region_end();
}
