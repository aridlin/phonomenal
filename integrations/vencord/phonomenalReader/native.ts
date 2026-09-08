/* SPDX-License-Identifier: GPL-3.0-or-later */
import { ChildProcessWithoutNullStreams, spawn } from "child_process";
import type { IpcMainInvokeEvent } from "electron";
import { access, readdir } from "fs/promises";
import { homedir } from "os";
import { basename, join, resolve } from "path";

let current: ChildProcessWithoutNullStreams | undefined;
let generation = 0;
function paths(root: string) {
    const directory = resolve(root || process.env.PHONOMENAL_HOME || join(homedir(), "dev/codexp/phonomenal"));
    return { directory, packs: join(directory, "data/packages") };
}
export async function voices(_event: IpcMainInvokeEvent, root: string) {
    const entries = await readdir(paths(root).packs, { withFileTypes: true });
    return entries.filter(e => e.isFile() && e.name.endsWith(".vcpack") && !e.name.includes("legacy"))
        .map(e => e.name).sort();
}
export function cancel() { generation++; current?.kill(); current = undefined; }
export async function synthesize(event: IpcMainInvokeEvent, root: string, voice: string, text: string) {
    cancel(); const token = generation;
    if (typeof text !== "string" || !text.trim() || text.length > 2000) throw new Error("Speech must contain 1–2000 characters.");
    if (voice !== basename(voice) || !(await voices(event, root)).includes(voice)) throw new Error("Unknown voice pack.");
    const { directory, packs } = paths(root);
    const name = process.platform === "win32" ? "phonomenal_splicer_cli.exe" : "phonomenal_splicer_cli";
    const candidates = [join(directory, "cpp/build-vcpack", name), join(directory, "cpp/build", name), join(directory, "bin", name), join(directory, name)];
    let executable = "";
    for (const candidate of candidates) { try { await access(candidate); executable = candidate; break; } catch { /* next layout */ } }
    if (!executable) throw new Error("Phonomenal C++ player was not found. Set the project/release directory in settings.");
    if (token !== generation) throw new Error("Speech generation cancelled.");
    return new Promise<string>((resolveAudio, reject) => {
        const child = current = spawn(executable, ["--bank", join(packs, voice), "--stdin", "--stdout-wav"], { shell: false, windowsHide: true });
        const chunks: Buffer[] = []; let size = 0; let error = ""; let failure = "";
        const timeout = setTimeout(() => { failure = "Speech generation timed out."; child.kill(); }, 60_000);
        child.stdout.on("data", (chunk: Buffer) => {
            size += chunk.length;
            if (size > 32 * 1024 * 1024) { failure = "Generated audio exceeds 32 MiB."; child.kill(); return; }
            chunks.push(chunk);
        });
        child.stderr.on("data", chunk => { error = (error + chunk.toString()).slice(-2000); });
        child.on("error", err => { clearTimeout(timeout); if (current === child) current = undefined; reject(err); });
        child.on("close", code => {
            clearTimeout(timeout); if (current === child) current = undefined;
            if (failure || code !== 0) { reject(new Error(failure || error || "Speech generation cancelled.")); return; }
            const wav = Buffer.concat(chunks);
            if (wav.toString("ascii", 0, 4) !== "RIFF" || wav.toString("ascii", 8, 12) !== "WAVE") { reject(new Error("Invalid player output.")); return; }
            resolveAudio(wav.toString("base64"));
        });
        child.stdin.on("error", () => {});
        child.stdin.end(text + "\n");
    });
}
