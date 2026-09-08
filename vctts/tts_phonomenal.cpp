#include "tts_phonomenal.h"
#include "custom_tts.h"
#include "phonomenal_splicer/splicer.h"
#include <algorithm>
#include <memory>
#include <mutex>
#include <windows.h>
namespace tts_phonomenal {
namespace {
struct Entry {std::filesystem::path path;std::wstring label;};
std::mutex catalog_mutex,engine_mutex;
std::filesystem::path catalog_directory,cached_path;
std::filesystem::file_time_type catalog_time{},cached_time{};
std::vector<Entry> catalog;
std::unique_ptr<phonomenal_splicer::VoiceBank> engine;
bool is_bank(const std::filesystem::path& path){return path.extension()==L".vcpack"||path.extension()==L".phbank";}
std::vector<Entry> entries(const std::filesystem::path& directory){
    std::lock_guard lock(catalog_mutex);std::error_code ec;
    auto stamp=std::filesystem::last_write_time(directory,ec);
    if(ec||directory.empty())return {};
    if(directory==catalog_directory&&stamp==catalog_time)return catalog;
    catalog.clear();catalog_directory=directory;catalog_time=stamp;
    for(const auto& entry:std::filesystem::directory_iterator(directory,ec)) {
        if(!entry.is_regular_file(ec)||!is_bank(entry.path()))continue;
        if(entry.path().extension()==L".phbank"&&std::filesystem::exists(directory/(entry.path().stem().wstring()+L".vcpack")))continue;
        try{auto bank=phonomenal_splicer::VoiceBank::Load(entry.path());catalog.push_back({entry.path(),custom_tts::Utf8ToWide(bank.merc())});}catch(const std::exception&){/* Invalid packs cannot become selectable voices. */}
    }
    std::sort(catalog.begin(),catalog.end(),[](const auto& a,const auto& b){return a.path<b.path;});return catalog;
}
bool has_banks(const std::filesystem::path& directory){std::error_code ec;if(!std::filesystem::is_directory(directory,ec))return false;for(const auto& e:std::filesystem::directory_iterator(directory,ec))if(is_bank(e.path()))return true;return false;}
}
std::filesystem::path discover_bank_directory(){wchar_t buffer[32768]{};GetModuleFileNameW(nullptr,buffer,32768);std::vector<std::filesystem::path> roots{std::filesystem::path(buffer).parent_path(),std::filesystem::current_path()};for(auto root:roots)for(int i=0;i<5;++i,root=root.parent_path())for(const auto& p:{root/L"data"/L"packages",root/L"packs",root/L"phonomenal"/L"data"/L"packages"})if(has_banks(p))return p;return {};}
std::vector<std::wstring> list_voice_labels(const std::filesystem::path& directory){std::vector<std::wstring> result;for(const auto& e:entries(directory.empty()?discover_bank_directory():directory))result.push_back(e.label);return result;}
std::wstring voice_id_for_index(int index){std::lock_guard lock(catalog_mutex);if(index<0||static_cast<std::size_t>(index)>=catalog.size())return {};return catalog[static_cast<std::size_t>(index)].path.stem().wstring();}
std::filesystem::path bank_path_for_index(const std::filesystem::path& directory,int index){auto voices=entries(directory);if(index<0||static_cast<std::size_t>(index)>=voices.size())return {};return voices[static_cast<std::size_t>(index)].path;}
bool bank_exists_for_index(const std::filesystem::path& directory,int index){return !bank_path_for_index(directory,index).empty();}
int available_bank_count(const std::filesystem::path& directory){return static_cast<int>(entries(directory).size());}
SpeakResult speak_wav(const std::wstring& text,const std::filesystem::path& path){SpeakResult result;try{std::lock_guard lock(engine_mutex);if(path.empty())throw std::runtime_error("Select a valid .vcpack voice first");auto stamp=std::filesystem::last_write_time(path);if(!engine||cached_path!=path||cached_time!=stamp){engine=std::make_unique<phonomenal_splicer::VoiceBank>(phonomenal_splicer::VoiceBank::Load(path));cached_path=path;cached_time=stamp;}auto plan=engine->PlanText(custom_tts::WideToUtf8(text));result.audio=engine->SynthesizeWav(plan);result.status=std::to_wstring(plan.units.size())+L" recorded chunks";for(const auto& warning:plan.warnings)result.status+=L" | "+custom_tts::Utf8ToWide(warning);}catch(const std::exception& e){result.error=custom_tts::Utf8ToWide(e.what());}return result;}
} // namespace tts_phonomenal
