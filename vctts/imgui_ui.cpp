#include "imgui_ui.h"
#include "custom_tts.h"
#include "tts_winrt.h"
#include "tts_phonomenal.h"
#include "audio_devices.h"

#include <cstring>
#include <filesystem>

namespace {

const char* EngineLabel(TtsEngine engine)
{
    switch (engine) {
    case TtsEngine::System:
        return "System";
    case TtsEngine::Custom:
        return "Custom Command";
    case TtsEngine::Phonomenal:
        return "Phonomenal";
    default:
        return "(unknown)";
    }
}

std::filesystem::path CurrentPhonomenalBankDirectory(const AppState& s)
{
    if (s.phonomenalBankDirectory[0] == '\0') {
        return {};
    }
    return std::filesystem::path(custom_tts::Utf8ToWide(s.phonomenalBankDirectory));
}

void EnsureVoiceLists(AppState& s)
{
    if (s.systemVoices.empty()) {
        s.systemVoices = tts_winrt::list_voices();
    }
    if (s.phonomenalVoices.empty()) {
        s.phonomenalVoices = tts_phonomenal::list_voice_labels(CurrentPhonomenalBankDirectory(s));
    }
    if (s.phonomenalBankDirectory[0] == '\0') {
        const auto discovered = tts_phonomenal::discover_bank_directory();
        if (!discovered.empty()) {
            const auto utf8 = custom_tts::WideToUtf8(discovered.wstring());
            strncpy_s(s.phonomenalBankDirectory, utf8.c_str(), _TRUNCATE);
        }
    }
}

}  // namespace

void ImGuiUi::init(HWND hwnd, D3D11Renderer& r)
{
    IMGUI_CHECKVERSION();
    ImGui::CreateContext();
    ImGui::StyleColorsDark();

    ImGui_ImplWin32_Init(hwnd);
    ImGui_ImplDX11_Init(r.device, r.ctx);
}

void ImGuiUi::shutdown()
{
    ImGui_ImplDX11_Shutdown();
    ImGui_ImplWin32_Shutdown();
    ImGui::DestroyContext();
}

UiAction ImGuiUi::draw(AppState& s)
{
    ImGui_ImplDX11_NewFrame();
    ImGui_ImplWin32_NewFrame();
    ImGui::NewFrame();

    UiAction action = UiAction::None;

    if (!s.configDone.load())
        action = draw_config(s);
    else
        action = draw_recording(s);

    ImGui::Render();
    return action;
}

UiAction ImGuiUi::draw_config(AppState& s)
{
    ImGui::SetNextWindowSize(ImVec2(720, 380), ImGuiCond_Always);
    ImGui::Begin("TTS Voice Typing - Config", nullptr,
        ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoCollapse);

    if (ImGui::Button("Quit")) {
        ImGui::End();
        return UiAction::Quit;
    }

    ImGui::Separator();
    ImGui::TextUnformatted("Startup config");
    ImGui::TextDisabled("Pick TWO output devices (miniaudio/WASAPI).");

    if (ImGui::Button("Refresh devices")) {
        RefreshOutputDevices(s);
    }

    EnsureVoiceLists(s);

    ImGui::Spacing();

    if (s.outDevicesUtf8.empty()) {
        ImGui::TextColored(ImVec4(1, 0.6f, 0.6f, 1), "No output devices found.");
        ImGui::TextDisabled("Press Refresh devices.");
        ImGui::End();
        return UiAction::None;
    }

    if (s.devA < 0) s.devA = 0;
    if (s.devB < 0) s.devB = 0;
    if (s.devA >= (int)s.outDevicesUtf8.size()) s.devA = 0;
    if (s.devB >= (int)s.outDevicesUtf8.size()) s.devB = 0;

    ImGui::TextUnformatted("Device A:");
    if (ImGui::BeginCombo("##devA", s.outDevicesUtf8[s.devA].c_str())) {
        for (int i = 0; i < (int)s.outDevicesUtf8.size(); i++) {
            bool sel = (i == s.devA);
            if (ImGui::Selectable(s.outDevicesUtf8[i].c_str(), sel))
                s.devA = i;
            if (sel) ImGui::SetItemDefaultFocus();
        }
        ImGui::EndCombo();
    }

    ImGui::TextUnformatted("Device B:");
    if (ImGui::BeginCombo("##devB", s.outDevicesUtf8[s.devB].c_str())) {
        for (int i = 0; i < (int)s.outDevicesUtf8.size(); i++) {
            bool sel = (i == s.devB);
            if (ImGui::Selectable(s.outDevicesUtf8[i].c_str(), sel))
                s.devB = i;
            if (sel) ImGui::SetItemDefaultFocus();
        }
        ImGui::EndCombo();
    }

    ImGui::Separator();
    ImGui::TextDisabled("Hotkeys work after you press Start.");
    bool useKeyless = s.useKeylessBackup.load();
    const char* keylessLabel = useKeyless ? "Keyless backup: ON" : "Keyless backup: OFF";
    if (ImGui::Button(keylessLabel)) {
        s.useKeylessBackup.store(!useKeyless);
    }
    ImGui::SameLine();
    ImGui::TextDisabled("Uses an online keyless TTS if enabled.");
    ImGui::Separator();
    ImGui::TextUnformatted("TTS Engine:");
    const char* enginePreview = EngineLabel(s.ttsEngine);
    if (ImGui::BeginCombo("##ttsEngine", enginePreview)) {
        constexpr TtsEngine engines[] = {
            TtsEngine::System,
            TtsEngine::Custom,
            TtsEngine::Phonomenal,
        };
        for (TtsEngine engine : engines) {
            const bool selected = (engine == s.ttsEngine);
            if (ImGui::Selectable(EngineLabel(engine), selected)) {
                s.ttsEngine = engine;
            }
            if (selected) {
                ImGui::SetItemDefaultFocus();
            }
        }
        ImGui::EndCombo();
    }

    if (s.ttsEngine == TtsEngine::System && !s.systemVoices.empty())
    {
        ImGui::TextUnformatted("System Voice:");

        static std::string voiceLabel;

        if (s.systemVoiceIndex >= 0 &&
            s.systemVoiceIndex < (int)s.systemVoices.size())
        {
            voiceLabel = custom_tts::WideToUtf8(s.systemVoices[s.systemVoiceIndex]);
        }
        else
        {
            voiceLabel = "(invalid)";
        }

        if (ImGui::BeginCombo("##systemVoice", voiceLabel.c_str()))
        {
            for (int i = 0; i < (int)s.systemVoices.size(); i++)
            {
                bool sel = (i == s.systemVoiceIndex);
                std::string name = custom_tts::WideToUtf8(s.systemVoices[i]);

                if (ImGui::Selectable(name.c_str(), sel))
                {
                    s.systemVoiceIndex = i;
                    tts_winrt::set_voice_index(i);
                }

                if (sel)
                    ImGui::SetItemDefaultFocus();
            }
            ImGui::EndCombo();
        }
    }
    else if (s.ttsEngine == TtsEngine::Custom)
    {
        ImGui::InputText("Command", s.customTtsCommand, sizeof(s.customTtsCommand));
        ImGui::TextDisabled("e.g. C:\\path\\customtts.exe {text}");
    }
    else if (s.ttsEngine == TtsEngine::Phonomenal)
    {
        auto bankDirectory = CurrentPhonomenalBankDirectory(s);
        const int availableBanks = tts_phonomenal::available_bank_count(bankDirectory);

        if (ImGui::InputText("Bank Directory", s.phonomenalBankDirectory, sizeof(s.phonomenalBankDirectory))) {
            bankDirectory = CurrentPhonomenalBankDirectory(s);
            s.phonomenalVoices = tts_phonomenal::list_voice_labels(bankDirectory);
            s.phonomenalVoiceIndex = 0;
        }
        if (ImGui::Button("Auto-detect Banks")) {
            const auto discovered = tts_phonomenal::discover_bank_directory();
            if (!discovered.empty()) {
                const auto utf8 = custom_tts::WideToUtf8(discovered.wstring());
                strncpy_s(s.phonomenalBankDirectory, utf8.c_str(), _TRUNCATE);
                bankDirectory = discovered;
                s.phonomenalVoices = tts_phonomenal::list_voice_labels(bankDirectory);
                s.phonomenalVoiceIndex = 0;
            }
        }
        ImGui::SameLine();
        ImGui::TextDisabled("%d voice packs available", availableBanks);

        { std::lock_guard lock(s.phonomenalStatusMutex); ImGui::TextWrapped("%s", s.phonomenalStatus.c_str()); }

        if (!s.phonomenalVoices.empty()) {
            if (s.phonomenalVoiceIndex < 0) s.phonomenalVoiceIndex = 0;
            if (s.phonomenalVoiceIndex >= (int)s.phonomenalVoices.size()) s.phonomenalVoiceIndex = 0;

            std::string preview(
                custom_tts::WideToUtf8(s.phonomenalVoices[s.phonomenalVoiceIndex])
            );
            if (!tts_phonomenal::bank_exists_for_index(bankDirectory, s.phonomenalVoiceIndex)) {
                preview += " (missing bank)";
            }

            ImGui::TextUnformatted("Voice:");
            if (ImGui::BeginCombo("##phonomenalVoice", preview.c_str())) {
                for (int i = 0; i < (int)s.phonomenalVoices.size(); ++i) {
                    bool sel = (i == s.phonomenalVoiceIndex);
                    std::string label = custom_tts::WideToUtf8(s.phonomenalVoices[i]);
                    if (!tts_phonomenal::bank_exists_for_index(bankDirectory, i)) {
                        label += " (missing bank)";
                    }
                    if (ImGui::Selectable(label.c_str(), sel)) {
                        s.phonomenalVoiceIndex = i;
                    }
                    if (sel) {
                        ImGui::SetItemDefaultFocus();
                    }
                }
                ImGui::EndCombo();
            }

            const auto selectedBank = tts_phonomenal::bank_path_for_index(bankDirectory, s.phonomenalVoiceIndex);
            std::string selectedBankUtf8 = custom_tts::WideToUtf8(selectedBank.wstring());
            ImGui::TextDisabled("Selected bank: %s", selectedBankUtf8.empty() ? "(none)" : selectedBankUtf8.c_str());
        }
    }

    if (ImGui::Button("Start")) {
        s.configDone.store(true);
        ImGui::End();
        return UiAction::StartFromConfig;
    }

    ImGui::SameLine();
    if (ImGui::Button("Test Tone")) {
        ImGui::End();
        return UiAction::TestTone;
    }

    ImGui::SameLine();
    if (ImGui::Button("Test TTS")) {
        ImGui::End();
        return UiAction::TestTts;
    }

    ImGui::End();
    return UiAction::None;
}

UiAction ImGuiUi::draw_recording(AppState& s)
{
    ImGui::SetNextWindowSize(ImVec2(700, 320), ImGuiCond_Always);
    ImGui::Begin("Voice Typing", nullptr,
        ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoCollapse);

    if (ImGui::Button("Quit")) {
        ImGui::End();
        return UiAction::Quit;
    }

    ImGui::SameLine();
    ImGui::TextDisabled("Toggle: Ctrl+Backspace | Stop: Enter | Exit: Ctrl+Shift+Tab+E");

    ImGui::Separator();
    ImGui::TextDisabled("Recording: %s", s.recording.load() ? "YES" : "no");
    ImGui::TextDisabled("Keyless backup: %s", s.useKeylessBackup.load() ? "ON" : "OFF");
    ImGui::TextDisabled("Engine: %s", EngineLabel(s.ttsEngine));
    if (s.ttsEngine == TtsEngine::System &&
        s.systemVoiceIndex >= 0 &&
        s.systemVoiceIndex < (int)s.systemVoices.size()) {
        std::string voice = custom_tts::WideToUtf8(s.systemVoices[s.systemVoiceIndex]);
        ImGui::TextDisabled("Voice: %s", voice.c_str());
    } else if (s.ttsEngine == TtsEngine::Phonomenal &&
               s.phonomenalVoiceIndex >= 0 &&
               s.phonomenalVoiceIndex < (int)s.phonomenalVoices.size()) {
        std::string voice = custom_tts::WideToUtf8(s.phonomenalVoices[s.phonomenalVoiceIndex]);
        ImGui::TextDisabled("Voice: %s", voice.c_str());
    }

    std::wstring copy = s.copyBuffer();
    std::string preview = AppState::sanitizePreview(copy);

    ImGui::TextUnformatted("Preview:");
    ImGui::BeginChild("##preview", ImVec2(0, 210), true);
    ImGui::TextUnformatted(preview.c_str());
    ImGui::EndChild();

    if (ImGui::Button("Stop & Speak")) {
        ImGui::End();
        return UiAction::StopRecording;
    }

    ImGui::End();
    return UiAction::None;
}
