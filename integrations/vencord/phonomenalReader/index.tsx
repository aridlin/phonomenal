/* SPDX-License-Identifier: GPL-3.0-or-later */
import { ChatBarButton, ChatBarButtonFactory } from "@api/ChatButtons";
import { definePluginSettings } from "@api/Settings";
import definePlugin, { IconComponent, OptionType, PluginNative } from "@utils/types";
import type { Message } from "@vencord/discord-types";
import { React, SelectedChannelStore, Toasts, UserStore } from "@webpack/common";

const Native = VencordNative.pluginHelpers.PhonomenalReader as PluginNative<typeof import("./native")>;
const settings = definePluginSettings({
    root: { type: OptionType.STRING, description: "Phonomenal project/release directory. Blank uses PHONOMENAL_HOME or ~/dev/codexp/phonomenal.", default: "" },
    userVoices: { type: OptionType.STRING, description: "One USER_ID=voice.vcpack per line. Other users get a stable voice derived from their ID.", multiline: true, default: "",
        isValid: (value: string) => value.split("\n").every(line => !line.trim() || /^\d{17,20}=[^/\\=]+\.vcpack$/.test(line.trim())) || "Use USER_ID=voice.vcpack, one per line." },
    voicePool: { type: OptionType.STRING, description: "Optional comma-separated pack filenames for automatic voices. Blank uses every available pack.", default: "" },
    volume: { type: OptionType.SLIDER, description: "Local speech volume", markers: [0, 25, 50, 75, 100], default: 75, stickToMarkers: false }
});
let channelId: string | undefined;
let epoch = 0; let armedAt = 0; let running = false;
let audio: HTMLAudioElement | undefined; let finishAudio: (() => void) | undefined;
let voiceList: string[] = [];
const queue: { user: string; text: string; epoch: number; }[] = [];
const seen = new Set<string>();
const listeners = new Set<() => void>();
const notify = (message: string) => Toasts.show({ id: Toasts.genId(), message, type: Toasts.Type.MESSAGE });
function reset() {
    epoch++; channelId = undefined; queue.length = 0;
    audio?.pause(); if (audio) audio.src = ""; audio = undefined;
    finishAudio?.(); finishAudio = undefined;
    void Native.cancel(); listeners.forEach(fn => fn());
}
function hash(text: string) {
    let value = 2166136261;
    for (let i = 0; i < text.length; i++) value = Math.imul(value ^ text.charCodeAt(i), 16777619);
    return value >>> 0;
}
function voiceFor(user: string) {
    const override = settings.store.userVoices.split("\n").map(s => s.trim().split("=")).find(([id]) => id === user)?.[1];
    if (override) {
        if (!voiceList.includes(override)) throw new Error(`Configured voice ${override} is unavailable.`);
        return override;
    }
    const pool = settings.store.voicePool.split(",").map(s => s.trim()).filter(Boolean);
    const voices = voiceList.filter(v => !pool.length || pool.includes(v));
    if (!voices.length) throw new Error("No available packs match the configured voice pool.");
    return voices.reduce((best, name) => hash(`${user}|${name}`) > hash(`${user}|${best}`) ? name : best);
}
async function drain() {
    if (running) return;
    running = true;
    try {
        while (queue.length && channelId) {
            const item = queue.shift()!;
            try {
                const wav = await Native.synthesize(settings.store.root, voiceFor(item.user), item.text);
                if (item.epoch !== epoch || channelId !== SelectedChannelStore.getChannelId()) continue;
                const player = audio = new Audio(`data:audio/wav;base64,${wav}`);
                player.volume = Math.max(0, Math.min(1, settings.store.volume / 100));
                await new Promise<void>((resolve, reject) => {
                    finishAudio = resolve; player.onended = () => resolve();
                    player.onerror = () => reject(new Error("Could not play generated speech."));
                    void player.play().catch(reject);
                });
                player.src = ""; if (audio === player) audio = undefined; finishAudio = undefined;
            } catch (error) {
                if (item.epoch === epoch) notify(`Phonomenal: ${String(error)}`);
            }
        }
    } finally { running = false; }
}
async function toggle(id: string) {
    const enabled = channelId === id; reset(); if (enabled) return;
    const token = epoch;
    try {
        voiceList = await Native.voices(settings.store.root);
        if (token !== epoch || SelectedChannelStore.getChannelId() !== id) return;
        if (!voiceList.length) throw new Error("No .vcpack files found in data/packages.");
        channelId = id; armedAt = Date.now(); seen.clear(); listeners.forEach(fn => fn());
        notify("Phonomenal will read new incoming messages in this channel.");
    } catch (error) { notify(`Phonomenal: ${String(error)}`); }
}
const Speaker: IconComponent = ({ height = 20, width = 20 }) => <svg width={width} height={height} viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 9v6h4l5 4V5L7 9H3zm12-2v2a4 4 0 0 1 0 6v2a6 6 0 0 0 0-10zm3-3v2a8 8 0 0 1 0 12v2a10 10 0 0 0 0-16z" /></svg>;
const Button: ChatBarButtonFactory = ({ channel, isMainChat }) => {
    const [, update] = React.useReducer(n => n + 1, 0);
    React.useEffect(() => { listeners.add(update); return () => { listeners.delete(update); }; }, []);
    if (!isMainChat) return null;
    const enabled = channelId === channel.id;
    return <ChatBarButton tooltip={enabled ? "Stop Phonomenal reading this channel" : "Read this channel with Phonomenal"} onClick={() => void toggle(channel.id)} buttonProps={{ "aria-pressed": enabled }}><span style={{ color: enabled ? "#b8bb26" : undefined }}><Speaker /></span></ChatBarButton>;
};
export default definePlugin({
    name: "PhonomenalReader", description: "Read new channel messages locally with per-user Phonomenal voices. Toggle with the speaker button.",
    authors: [{ name: "Aridlin", id: 0n }], settings,
    chatBarButton: { render: Button, icon: Speaker },
    start() { reset(); }, stop() { reset(); },
    flux: {
        CHANNEL_SELECT() { if (channelId && channelId !== SelectedChannelStore.getChannelId()) reset(); },
        MESSAGE_CREATE({ message, optimistic }: { message: Message; optimistic?: boolean; }) {
            if (!channelId || message.channel_id !== channelId || optimistic || message.author.id === UserStore.getCurrentUser()?.id || seen.has(message.id)) return;
            // Reject history/reconnect replays and system messages.
            if (Number((BigInt(message.id) >> 22n) + 1420070400000n) < armedAt || ![0, 19].includes(message.type)) return;
            seen.add(message.id); if (seen.size > 2000) seen.delete(seen.values().next().value!);
            const text = message.content.replace(/```[\s\S]*?```/g, " code block ").replace(/https?:\/\/\S+/g, " link ")
                .replace(/<@!?(\d+)>/g, (_, id) => UserStore.getUser(id)?.username || "someone")
                .replace(/<a?:([^:]+):\d+>/g, "$1").replace(/[*_~`|]/g, "").trim();
            if (!text) return;
            const parts = text.match(/.{1,1000}(?:\s|$)|.{1,1000}/gs) || [];
            if (queue.length + parts.length > 30) { notify("Phonomenal queue is full; skipped a message."); return; }
            for (const part of parts) queue.push({ user: message.author.id, text: part.trim(), epoch });
            void drain();
        }
    }
});
