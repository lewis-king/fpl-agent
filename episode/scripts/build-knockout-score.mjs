import {writeFileSync} from 'node:fs';
import {resolve} from 'node:path';

const SAMPLE_RATE = 48_000;
const DURATION = 140;
const LENGTH = SAMPLE_RATE * DURATION;
const left = new Float32Array(LENGTH);
const right = new Float32Array(LENGTH);

const beat = 60 / 128;
const TAU = Math.PI * 2;
let noiseState = 0x51f15e;

const noise = () => {
  noiseState = (Math.imul(noiseState, 1_664_525) + 1_013_904_223) >>> 0;
  return (noiseState / 0xffffffff) * 2 - 1;
};

const midi = (note) => 440 * 2 ** ((note - 69) / 12);
const softClip = (sample) => Math.tanh(sample * 1.12);

const panGains = (pan) => {
  const angle = ((Math.max(-1, Math.min(1, pan)) + 1) * Math.PI) / 4;
  return [Math.cos(angle), Math.sin(angle)];
};

const envelope = (time, duration, attack, release) => {
  const attackGain = attack <= 0 ? 1 : Math.min(1, time / attack);
  const releaseGain = release <= 0 ? 1 : Math.min(1, (duration - time) / release);
  return Math.max(0, Math.min(attackGain, releaseGain));
};

const addTone = ({
  start,
  duration,
  note,
  frequency = note === undefined ? 220 : midi(note),
  gain = 0.1,
  pan = 0,
  wave = 'sine',
  attack = 0.008,
  release = 0.08,
  vibrato = 0,
  vibratoRate = 5.2,
}) => {
  const from = Math.max(0, Math.floor(start * SAMPLE_RATE));
  const to = Math.min(LENGTH, Math.ceil((start + duration) * SAMPLE_RATE));
  const [gainL, gainR] = panGains(pan);
  let phase = 0;
  for (let index = from; index < to; index += 1) {
    const time = (index - from) / SAMPLE_RATE;
    const localFrequency = frequency * (1 + Math.sin(TAU * vibratoRate * time) * vibrato);
    phase += (TAU * localFrequency) / SAMPLE_RATE;
    const cycle = (phase / TAU) % 1;
    let sample;
    if (wave === 'triangle') sample = 1 - 4 * Math.abs(Math.round(cycle) - cycle);
    else if (wave === 'saw') sample = 2 * (cycle - Math.floor(cycle + 0.5));
    else if (wave === 'square') sample = Math.sin(phase) >= 0 ? 1 : -1;
    else sample = Math.sin(phase);
    const env = envelope(time, duration, attack, release);
    const value = sample * gain * env;
    left[index] += value * gainL;
    right[index] += value * gainR;
  }
};

const addKick = (start, gain = 0.72) => {
  const duration = 0.28;
  const from = Math.floor(start * SAMPLE_RATE);
  const to = Math.min(LENGTH, Math.ceil((start + duration) * SAMPLE_RATE));
  let phase = 0;
  for (let index = from; index < to; index += 1) {
    if (index < 0) continue;
    const time = (index - from) / SAMPLE_RATE;
    const frequency = 46 + 105 * Math.exp(-time * 28);
    phase += (TAU * frequency) / SAMPLE_RATE;
    const body = Math.sin(phase) * Math.exp(-time * 15);
    const click = noise() * Math.exp(-time * 85) * 0.11;
    left[index] += (body + click) * gain;
    right[index] += (body + click) * gain;
  }
};

const addSnare = (start, gain = 0.22) => {
  const duration = 0.2;
  const from = Math.floor(start * SAMPLE_RATE);
  const to = Math.min(LENGTH, Math.ceil((start + duration) * SAMPLE_RATE));
  let phase = 0;
  for (let index = from; index < to; index += 1) {
    if (index < 0) continue;
    const time = (index - from) / SAMPLE_RATE;
    phase += (TAU * 178) / SAMPLE_RATE;
    const value = (noise() * 0.82 + Math.sin(phase) * 0.18) * Math.exp(-time * 19) * gain;
    left[index] += value * 0.92;
    right[index] += value;
  }
};

const addHat = (start, gain = 0.065, open = false, pan = 0) => {
  const duration = open ? 0.16 : 0.055;
  const from = Math.floor(start * SAMPLE_RATE);
  const to = Math.min(LENGTH, Math.ceil((start + duration) * SAMPLE_RATE));
  const [gainL, gainR] = panGains(pan);
  let previous = 0;
  for (let index = from; index < to; index += 1) {
    if (index < 0) continue;
    const time = (index - from) / SAMPLE_RATE;
    const raw = noise();
    const high = raw - previous * 0.84;
    previous = raw;
    const value = high * Math.exp(-time * (open ? 22 : 72)) * gain;
    left[index] += value * gainL;
    right[index] += value * gainR;
  }
};

const addImpact = (start, gain = 0.78, pan = 0) => {
  addKick(start, gain);
  addTone({start, duration: 1.3, frequency: 58, gain: gain * 0.28, pan, wave: 'sine', attack: 0.002, release: 1.25});
  const from = Math.floor(start * SAMPLE_RATE);
  const duration = 0.85;
  const to = Math.min(LENGTH, Math.ceil((start + duration) * SAMPLE_RATE));
  const [gainL, gainR] = panGains(pan);
  for (let index = from; index < to; index += 1) {
    if (index < 0) continue;
    const time = (index - from) / SAMPLE_RATE;
    const value = noise() * Math.exp(-time * 7.5) * gain * 0.17;
    left[index] += value * gainL;
    right[index] += value * gainR;
  }
};

const addRiser = (start, duration, gain = 0.11) => {
  const from = Math.floor(start * SAMPLE_RATE);
  const to = Math.min(LENGTH, Math.ceil((start + duration) * SAMPLE_RATE));
  let filtered = 0;
  for (let index = from; index < to; index += 1) {
    if (index < 0) continue;
    const time = (index - from) / SAMPLE_RATE;
    const progress = time / duration;
    filtered = filtered * (0.92 - progress * 0.12) + noise() * (0.08 + progress * 0.12);
    const value = filtered * progress ** 1.7 * gain;
    const pan = Math.sin(progress * Math.PI * 5) * 0.55;
    const [gainL, gainR] = panGains(pan);
    left[index] += value * gainL;
    right[index] += value * gainR;
  }
};

const chord = (start, duration, notes, gain = 0.045, wave = 'triangle', pan = 0) => {
  notes.forEach((note, index) =>
    addTone({
      start: start + index * 0.012,
      duration,
      note,
      gain,
      pan: pan + (index - (notes.length - 1) / 2) * 0.22,
      wave,
      attack: 0.18,
      release: Math.min(0.55, duration * 0.42),
      vibrato: 0.0018,
    }),
  );
};

const bass = (start, note, duration = beat * 0.78, gain = 0.19) => {
  addTone({start, duration, note, gain, wave: 'triangle', attack: 0.006, release: 0.12});
  addTone({start, duration: duration * 0.84, note: note - 12, gain: gain * 0.32, wave: 'sine', attack: 0.004, release: 0.14});
};

const motif = (start, root = 62, gain = 0.1, pan = 0) => {
  const steps = [0, 3, 7, 10, 7, 12];
  const lengths = [0.42, 0.32, 0.38, 0.28, 0.32, 0.68];
  let cursor = start;
  steps.forEach((step, index) => {
    addTone({
      start: cursor,
      duration: beat * lengths[index],
      note: root + step,
      gain: index === steps.length - 1 ? gain * 1.15 : gain,
      pan,
      wave: 'triangle',
      attack: 0.012,
      release: 0.12,
      vibrato: 0.002,
    });
    cursor += beat * (index === 5 ? 1.25 : 0.5);
  });
};

const addGroove = (start, end, {density = 1, drive = 1, rootPattern = [38, 38, 41, 36]} = {}) => {
  const bar = beat * 4;
  let barIndex = 0;
  for (let barStart = start; barStart < end - 0.1; barStart += bar, barIndex += 1) {
    const root = rootPattern[barIndex % rootPattern.length];
    for (let step = 0; step < 8; step += 1) {
      const at = barStart + step * beat * 0.5;
      if (at >= end) continue;
      if (step % 2 === 0 || density > 1.1) addHat(at, 0.038 * density, step === 7, step % 4 === 1 ? -0.35 : 0.35);
      if (step === 0 || step === 4 || (drive > 1.1 && step === 6)) addKick(at, 0.38 * drive);
      if (step === 2 || step === 6) addSnare(at, 0.15 * drive);
    }
    bass(barStart, root, beat * 0.72, 0.14 * drive);
    bass(barStart + beat * 1.5, root + (barIndex % 2 ? 5 : 7), beat * 0.38, 0.1 * drive);
    bass(barStart + beat * 2, root, beat * 0.7, 0.14 * drive);
    bass(barStart + beat * 3.25, root + 7, beat * 0.42, 0.1 * drive);
  }
};

const progression = [
  [50, 53, 57],
  [46, 50, 53],
  [41, 45, 48],
  [48, 52, 55],
];

const addProgression = (start, end, gain = 0.04, pulse = false) => {
  const chordLength = beat * 4;
  let index = 0;
  for (let at = start; at < end; at += chordLength, index += 1) {
    const notes = progression[index % progression.length];
    chord(at, Math.min(chordLength * 0.94, end - at), notes, gain, pulse ? 'saw' : 'triangle');
    if (pulse) {
      for (let eighth = 0; eighth < 8; eighth += 1) {
        addTone({start: at + eighth * beat * 0.5, duration: beat * 0.24, note: notes[1] + 12, gain: gain * 0.34, pan: eighth % 2 ? 0.42 : -0.42, wave: 'triangle', release: 0.06});
      }
    }
  }
};

// 0:00–0:07 — thousands of contenders arrive; the motif is teased before the beat drops.
chord(0, 6.8, [38, 45, 50, 53], 0.043, 'triangle');
for (let at = 0.4; at < 6.8; at += beat * 0.5) addHat(at, 0.014 + (at / 7) * 0.045, false, Math.sin(at * 2.1) * 0.6);
motif(1.2, 62, 0.07, -0.22);
addRiser(3.2, 3.8, 0.16);

// 0:07–0:30 — buoyant qualifying round: energetic, legible and playful.
addImpact(7, 0.72);
addProgression(7, 30, 0.038, true);
addGroove(7, 30, {density: 1, drive: 0.95});
for (let at = 8.2; at < 29; at += beat * 8) motif(at, 62, 0.085, (Math.floor(at) % 2 ? -0.28 : 0.28));
addRiser(27.8, 2.2, 0.14);

// 0:30–0:54 — head-to-head knockouts; the rhythm gains weight and elimination hits answer each other.
addImpact(30, 0.86);
addProgression(30, 54, 0.043, true);
addGroove(30, 54, {density: 1.2, drive: 1.1, rootPattern: [38, 38, 36, 41]});
for (let at = 32; at < 53; at += beat * 4) {
  addImpact(at, 0.25, Math.floor(at / 2) % 2 ? -0.55 : 0.55);
}
motif(34.4, 62, 0.09, -0.42);
motif(42, 62, 0.09, 0.42);
motif(49.5, 65, 0.095, 0);
addRiser(51.3, 2.7, 0.16);

// 0:54–1:12 — 25,000 futures: arpeggios churn while the groove stays propulsive.
addImpact(54, 0.8);
addProgression(54, 72, 0.034, false);
addGroove(54, 72, {density: 0.9, drive: 0.88, rootPattern: [38, 41, 36, 38]});
const arpNotes = [62, 65, 69, 72, 69, 65, 60, 65, 69, 72, 77, 72, 58, 62, 65, 70];
for (let step = 0, at = 54.15; at < 71.8; step += 1, at += beat * 0.25) {
  addTone({start: at, duration: beat * 0.2, note: arpNotes[step % arpNotes.length], gain: 0.045, pan: step % 2 ? 0.48 : -0.48, wave: 'triangle', attack: 0.004, release: 0.045});
}
addRiser(68.8, 3.2, 0.17);

// 1:12–1:31 — horizon invasion: stereo challenger motifs trade blows.
addImpact(72, 0.88);
addProgression(72, 91, 0.042, true);
addGroove(72, 91, {density: 1.15, drive: 1.05, rootPattern: [38, 46, 41, 48]});
for (let at = 73.4; at < 89.5; at += beat * 8) {
  motif(at, 62, 0.088, -0.62);
  motif(at + beat * 4, 65, 0.088, 0.62);
}
for (let at = 76; at < 90; at += beat * 4) addImpact(at, 0.23, Math.floor(at) % 2 ? -0.6 : 0.6);
addRiser(88, 3, 0.2);

// 1:31–1:55 — finals: faster hats, brighter motif and increasingly close impacts.
addImpact(91, 0.95);
addProgression(91, 115, 0.047, true);
addGroove(91, 115, {density: 1.42, drive: 1.16, rootPattern: [38, 41, 46, 48]});
for (let at = 91.2; at < 114.5; at += beat * 0.25) addHat(at, 0.025, false, Math.sin(at * 3.7) * 0.62);
motif(94, 62, 0.1, -0.38);
motif(101.5, 65, 0.105, 0.38);
motif(108.6, 67, 0.112, 0);
for (const at of [96, 102, 107, 111, 113.2, 114.15]) addImpact(at, 0.29 + (at - 96) * 0.006, at % 2 ? -0.35 : 0.35);
addRiser(111.5, 3.5, 0.24);

// 1:55–2:06 — last vetoes: the groove strips back to heartbeat, then launches upward.
addImpact(115, 0.98);
chord(115, 10.8, [38, 41, 45, 50], 0.045, 'triangle');
for (let at = 115; at < 126; at += beat) {
  addKick(at, 0.44 + (at - 115) * 0.012);
  addHat(at + beat * 0.5, 0.05 + (at - 115) * 0.002, false, at % 2 ? -0.4 : 0.4);
}
for (const [index, at] of [117.5, 120.4, 123.1, 124.7, 125.45].entries()) {
  addImpact(at, 0.35 + index * 0.06, index % 2 ? 0.45 : -0.45);
}
for (let step = 0; step < 16; step += 1) {
  addTone({start: 121.8 + step * 0.25, duration: 0.18, note: 62 + step, gain: 0.045 + step * 0.002, pan: step % 2 ? 0.38 : -0.38, wave: 'triangle', release: 0.07});
}
addRiser(121.5, 4.5, 0.3);

// 2:06–2:20 — champion: a major-key payoff, full groove and one final victorious statement.
addImpact(126, 1.12);
const victoryProgression = [
  [50, 54, 57],
  [45, 49, 52],
  [47, 50, 54],
  [43, 47, 50],
];
let victoryIndex = 0;
for (let at = 126; at < 140; at += beat * 4, victoryIndex += 1) {
  chord(at, beat * 3.8, victoryProgression[victoryIndex % victoryProgression.length], 0.058, 'triangle');
}
addGroove(126, 139.4, {density: 1.35, drive: 1.18, rootPattern: [38, 33, 35, 31]});
motif(126.8, 62, 0.13, -0.2);
motif(130.6, 66, 0.135, 0.2);
motif(134.4, 69, 0.145, 0);
chord(137.5, 2.5, [50, 54, 57, 62, 66], 0.072, 'triangle');
addImpact(137.5, 0.64);

// Master with a short fade and a conservative true-peak margin for video playback.
let peak = 0;
for (let index = 0; index < LENGTH; index += 1) {
  const time = index / SAMPLE_RATE;
  const fadeIn = Math.min(1, time / 0.35);
  const fadeOut = Math.min(1, (DURATION - time) / 1.6);
  const gain = Math.max(0, Math.min(fadeIn, fadeOut));
  left[index] = softClip(left[index] * 0.86) * gain;
  right[index] = softClip(right[index] * 0.86) * gain;
  peak = Math.max(peak, Math.abs(left[index]), Math.abs(right[index]));
}

const targetPeak = 0.82;
const scale = peak > targetPeak ? targetPeak / peak : 1;
const bytesPerSample = 2;
const blockAlign = bytesPerSample * 2;
const dataSize = LENGTH * blockAlign;
const output = Buffer.allocUnsafe(44 + dataSize);
output.write('RIFF', 0);
output.writeUInt32LE(36 + dataSize, 4);
output.write('WAVE', 8);
output.write('fmt ', 12);
output.writeUInt32LE(16, 16);
output.writeUInt16LE(1, 20);
output.writeUInt16LE(2, 22);
output.writeUInt32LE(SAMPLE_RATE, 24);
output.writeUInt32LE(SAMPLE_RATE * blockAlign, 28);
output.writeUInt16LE(blockAlign, 32);
output.writeUInt16LE(16, 34);
output.write('data', 36);
output.writeUInt32LE(dataSize, 40);

let offset = 44;
for (let index = 0; index < LENGTH; index += 1) {
  output.writeInt16LE(Math.round(Math.max(-1, Math.min(1, left[index] * scale)) * 32767), offset);
  output.writeInt16LE(Math.round(Math.max(-1, Math.min(1, right[index] * scale)) * 32767), offset + 2);
  offset += 4;
}

const outputPath = resolve(process.argv[2] ?? 'public/audio/fplagent-knockout-score-raw.wav');
writeFileSync(outputPath, output);
console.log(`Built ${outputPath} (${DURATION}s, 128 BPM, stereo)`);
