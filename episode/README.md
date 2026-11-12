# FPLAgent squad knockout film

A data-bound Remotion tournament showing named GW1 squads being drafted, eliminated and promoted
through FPLAgent's search, simulation, horizon, finals and publication stages.

The field gives every squad a composition-derived call sign—such as
`The Red Engine`, `The Milenković Shield` and `The Tanaka Lock`—while retaining the candidate hash
as its audit receipt. Names are regenerated from the current decision artifacts rather than typed
into the scenes.

The visible rounds are bound to current machine artifacts:

- 551,829 legal squads enter the draw;
- 10,000 multi-objective qualifiers become 512 residual survivors and 64 finalists;
- finalists play through 25,000 correlated futures;
- 64 incumbents meet 160 horizon challengers and protected neighbours;
- the real synthesis top eight contest quarterfinals, semifinals and the final;
- the champion must still pass structure, role and availability vetoes.

The episode reads current machine artifacts from `../data` through `scripts/build-data.mjs`.
It does not duplicate decision numbers by hand except for explicitly benchmarked acceleration
baselines documented in the technical whitepaper.

```bash
cd episode
npm install
npm run score
npm run studio
npm run still
npm run render
```

The composition is 1920×1080, 30fps and 140 seconds. The final assets are written to:

- `reports/fplagent-decision-episode.mp4`
- `reports/fplagent-decision-episode-poster.png`

The original soundtrack is deterministically synthesised at 128 BPM. Its sections align to the
actual round changes at 00:07, 00:30, 00:54, 01:12, 01:31, 01:55 and 02:06. The arrangement moves
from the challenger motif into a qualifying groove, heavier knockout drums, simulated-world
arpeggios, stereo horizon duels, accelerating finals, veto heartbeats and a major-key victory.

The final QA checks the full MP4 at five-second intervals and every scene boundary, plus stream
metadata, black-frame detection, silence detection, freeze detection and EBU R128 loudness. The
published master is 1080p/30fps with stereo 48 kHz audio; the current build measures -17.8 LUFS,
3.5 LU loudness range and -3.0 dBFS true peak.

Remotion uses a special license for some commercial organizations. This personal, non-commercial
research project falls within the intended free-use context, but review Remotion's current license
before changing the distribution model.
