#include "phonomenal_splicer/splicer.h"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <iomanip>
#include <iterator>
#include <stdexcept>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
static std::string quote(const std::string& s) {
    std::ostringstream o;o<<'"';for(unsigned char c:s){switch(c){case '"':o<<"\\\"";break;case '\\':o<<"\\\\";break;case '\n':o<<"\\n";break;case '\r':o<<"\\r";break;case '\t':o<<"\\t";break;default:if(c<32)o<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;else o<<c;}}o<<'"';return o.str();
}
static void print_plan(const phonomenal_splicer::PlanResult& p,std::ostream& o) {
    o<<"{\"voice\":"<<quote(p.merc)<<",\"normalized_text\":"<<quote(p.normalized_text)<<",\"sample_rate\":"<<p.sample_rate<<",\"score\":"<<p.score<<",\"warnings\":[";
    for(std::size_t i=0;i<p.warnings.size();++i){if(i)o<<',';o<<quote(p.warnings[i]);}o<<"],\"units\":[";
    for(std::size_t i=0;i<p.units.size();++i){const auto& u=p.units[i];if(i)o<<',';o<<"{\"kind\":"<<quote(phonomenal_splicer::UnitKindToString(u.kind))<<",\"target_text\":"<<quote(u.target_text)<<",\"text\":"<<quote(u.text)<<",\"clip_id\":"<<quote(u.clip_id)<<",\"start_sample\":"<<u.start_sample<<",\"end_sample\":"<<u.end_sample<<",\"pause_before_ms\":"<<u.pause_before_ms<<",\"approximate\":"<<(u.approximated?"true":"false")<<"}";}o<<"]}\n";
}
int main(int argc,char** argv) {
    try {
        std::filesystem::path bank_path,output_path;std::string text,phones;bool stdout_wav=false,plan_only=false,inspect=false,stdin_text=false;
        phonomenal_splicer::SynthesizeOptions options;
        for(int i=1;i<argc;++i){std::string arg=argv[i];auto value=[&]{if(++i>=argc)throw std::runtime_error("Missing value for "+arg);return std::string(argv[i]);};
            if(arg=="--bank")bank_path=value();else if(arg=="--text")text=value();else if(arg=="--phones")phones=value();else if(arg=="--output")output_path=value();else if(arg=="--stdout-wav")stdout_wav=true;else if(arg=="--plan")plan_only=true;else if(arg=="--inspect")inspect=true;else if(arg=="--stdin")stdin_text=true;else if(arg=="--strict")options.strict=true;else if(arg=="--beam")options.beam_width=std::stoul(value());else if(arg=="--help"||arg=="-h"){std::cout<<"phonomenal_splicer_cli --bank voice.vcpack (--text TEXT | --stdin | --phones PHONES) [--output speech.wav] [--stdout-wav] [--plan] [--strict]\nphonomenal_splicer_cli --bank voice.vcpack --inspect\n";return 0;}else throw std::runtime_error("Unknown argument: "+arg);
        }
        if(bank_path.empty())throw std::runtime_error("Expected --bank");
        if(stdin_text){if(!text.empty()||!phones.empty())throw std::runtime_error("--stdin cannot accompany --text/--phones");text.assign(std::istreambuf_iterator<char>(std::cin),{});}
        auto bank=phonomenal_splicer::VoiceBank::Load(bank_path);
        if(inspect){std::cout<<(bank.quality_report().empty()?"{}":bank.quality_report())<<'\n';return 0;}
        if(text.empty()==phones.empty())throw std::runtime_error("Expected exactly one of --text, --stdin or --phones");
        if(!stdout_wav&&!plan_only&&output_path.empty())throw std::runtime_error("Expected --output, --stdout-wav or --plan");
        std::vector<std::string> phone_list;std::istringstream in(phones);for(std::string p;in>>p;)phone_list.push_back(p);
        auto plan=!text.empty()?bank.PlanText(text,options):bank.PlanPhonemes(phone_list,options);
        if(plan_only)print_plan(plan,stdout_wav?std::cerr:std::cout);
        else for(const auto& warning:plan.warnings)std::cerr<<warning<<'\n';
        if(stdout_wav||!output_path.empty()) {
            auto wav=bank.SynthesizeWav(plan,options);
            if(stdout_wav){
#ifdef _WIN32
                _setmode(_fileno(stdout),_O_BINARY);
#endif
                std::cout.write(reinterpret_cast<const char*>(wav.data()),static_cast<std::streamsize>(wav.size()));if(!std::cout)throw std::runtime_error("Audio stdout failed");
            }
            if(!output_path.empty()){if(!output_path.parent_path().empty())std::filesystem::create_directories(output_path.parent_path());std::ofstream out(output_path,std::ios::binary);out.write(reinterpret_cast<const char*>(wav.data()),static_cast<std::streamsize>(wav.size()));if(!out)throw std::runtime_error("Could not write WAV");}
        }
        return 0;
    }catch(const std::exception& e){std::cerr<<"phonomenal: "<<e.what()<<'\n';return 1;}
}
