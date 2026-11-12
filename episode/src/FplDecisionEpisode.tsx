import {Audio} from '@remotion/media';
import type {CSSProperties, ReactNode} from 'react';
import {
  AbsoluteFill,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import episodeData from './data/episode-data.json';
import {
  appear,
  Caption,
  clamp,
  CountUp,
  Eyebrow,
  formatInt,
  formatSeconds,
  Metric,
  palette,
  ProgressChrome,
  SceneShell,
  SceneTitle,
  Shirt,
  TeamPitch,
} from './components';
import type {EpisodeData} from './types';

const data = episodeData as EpisodeData;

export const FPL_AGENT_EPISODE_FRAMES = 3750;

const CHAPTERS = [
  'THE PROBLEM',
  'THE EVIDENCE',
  'THE FORECAST',
  'THE SEARCH',
  'THE WORLDS',
  'THE HORIZON',
  'THE SYNTHESIS',
  'THE GAUNTLET',
  'THE WINNER',
  'THE RECEIPT',
];

const SCENES = {
  intro: {from: 0, duration: 270},
  evidence: {from: 240, duration: 390},
  forecast: {from: 600, duration: 330},
  search: {from: 900, duration: 600},
  worlds: {from: 1470, duration: 360},
  horizon: {from: 1800, duration: 390},
  synthesis: {from: 2160, duration: 450},
  gates: {from: 2580, duration: 450},
  reveal: {from: 3000, duration: 630},
  outro: {from: 3600, duration: 150},
} as const;

const CHAPTER_FRAMES = Object.values(SCENES).map((scene) => scene.from);

const sourceNodes = [
  {label: 'Official FPL', note: 'rules · prices · fixtures', authority: 'AUTHORITATIVE'},
  {label: 'Betfair market', note: 'team scoring priors', authority: 'BOUNDED'},
  {label: 'Understat', note: 'independent chance data', authority: 'SHADOW'},
  {label: 'Lineup consensus', note: 'role verification', authority: 'SHADOW'},
];

const candidateDots = Array.from({length: 520}, (_, index) => ({
  x: ((index * 73 + 19) % 997) / 997,
  y: ((index * 193 + 41) % 991) / 991,
  scale: 0.55 + (((index * 31) % 47) / 47) * 0.75,
  alpha: 0.2 + (((index * 17) % 43) / 43) * 0.64,
  survivor: index % 41 === 0 || index % 67 === 0,
}));

const worldRows = Array.from({length: 84}, (_, index) => ({
  y: 95 + ((index * 71) % 690),
  x: ((index * 149 + 33) % 820) - 20,
  width: 90 + ((index * 47) % 270),
  delay: (index * 13) % 80,
  good: index % 3 !== 0,
}));

const SceneIndex = ({index}: {index: number}) => (
  <div
    className="mono"
    style={{
      position: 'absolute',
      top: 144,
      right: 116,
      color: 'rgba(239,244,237,.16)',
      fontSize: 92,
      fontWeight: 620,
      letterSpacing: '-.07em',
    }}
  >
    {String(index).padStart(2, '0')}
  </div>
);

const IntroScene = () => {
  const frame = useCurrentFrame();
  const universe = interpolate(frame, [60, 196], [0, data.search.universe], clamp);
  const one = spring({frame: frame - 170, fps: 30, config: {damping: 17, mass: 0.8, stiffness: 95}});
  return (
    <SceneShell duration={SCENES.intro.duration}>
      <SceneIndex index={1} />
      <div style={{position: 'absolute', left: 112, top: 208, width: 1050}}>
        <div style={appear(frame, 8)}><Eyebrow>Gameweek one / the decision problem</Eyebrow></div>
        <h1
          style={{
            margin: '32px 0 25px',
            fontSize: 126,
            fontWeight: 560,
            lineHeight: .88,
            letterSpacing: '-.076em',
            ...appear(frame, 18, 58),
          }}
        >
          Hundreds of thousands enter.
          <br />One squad leaves.
        </h1>
        <p style={{maxWidth: 820, margin: 0, color: palette.muted, fontSize: 28, lineHeight: 1.4, ...appear(frame, 36)}}>
          The winner is not chosen from a player ranking. It must survive legality, uncertainty,
          exact FPL rules, future transfers and evidence that disagrees.
        </p>
      </div>
      <div
        style={{
          position: 'absolute',
          right: 112,
          bottom: 128,
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          alignItems: 'end',
          gap: 32,
          width: 800,
          paddingTop: 23,
          borderTop: `1px solid ${palette.line}`,
          ...appear(frame, 54, 26),
        }}
      >
        <div>
          <div className="mono" style={{color: palette.muted, fontSize: 14, letterSpacing: '.16em'}}>LEGAL SEARCH FIELD</div>
          <div className="mono" style={{marginTop: 9, fontSize: 77, fontWeight: 580, letterSpacing: '-.065em'}}>
            {formatInt(universe)}
          </div>
        </div>
        <div
          style={{
            width: 110,
            height: 110,
            display: 'grid',
            placeItems: 'center',
            borderRadius: 99,
            background: palette.greenPale,
            color: palette.ink,
            transform: `scale(${one})`,
            fontSize: 54,
            fontWeight: 720,
          }}
        >
          1
        </div>
      </div>
    </SceneShell>
  );
};

const EvidenceNode = ({
  label,
  note,
  authority,
  index,
}: {
  label: string;
  note: string;
  authority: string;
  index: number;
}) => {
  const frame = useCurrentFrame();
  const connected = interpolate(frame, [55 + index * 24, 90 + index * 24], [0, 1], clamp);
  return (
    <div style={{position: 'relative', display: 'grid', gridTemplateColumns: '340px 1fr', alignItems: 'center', gap: 26, ...appear(frame, 24 + index * 18, 30)}}>
      <div style={{padding: '24px 28px', borderRadius: 24, background: 'rgba(239,244,237,.055)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)'}}>
        <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14}}>
          <div style={{fontSize: 24, fontWeight: 650, letterSpacing: '-.025em'}}>{label}</div>
          <div className="mono" style={{color: authority === 'AUTHORITATIVE' ? palette.green : palette.amber, fontSize: 10, letterSpacing: '.13em'}}>{authority}</div>
        </div>
        <div style={{marginTop: 8, color: palette.muted, fontSize: 16}}>{note}</div>
      </div>
      <div style={{height: 1, transform: `scaleX(${connected})`, transformOrigin: 'left', background: `linear-gradient(90deg, ${palette.green}, rgba(130,173,138,.06))`}} />
    </div>
  );
};

const EvidenceScene = () => {
  const frame = useCurrentFrame();
  const lock = spring({frame: frame - 190, fps: 30, config: {damping: 16, stiffness: 110}});
  return (
    <SceneShell duration={SCENES.evidence.duration}>
      <SceneIndex index={2} />
      <div style={{position: 'absolute', left: 112, top: 164, width: 770}}>
        <SceneTitle
          eyebrow="Evidence before opinion"
          title={<>Nothing enters without a timestamp.</>}
          body={<>Every source receives an authority level, a checksum and a point-in-time boundary. Shadow evidence can challenge the model; it cannot quietly rewrite it.</>}
          width={760}
        />
      </div>
      <div style={{position: 'absolute', left: 930, top: 207, width: 780}}>
        <div style={{display: 'grid', gap: 18}}>
          {sourceNodes.map((node, index) => <EvidenceNode key={node.label} {...node} index={index} />)}
        </div>
        <div
          style={{
            margin: '34px 0 0 384px',
            width: 330,
            padding: '25px 27px',
            borderRadius: 28,
            background: palette.greenPale,
            color: palette.ink,
            boxShadow: 'inset 0 1px 0 white, 0 26px 60px -42px rgba(3,13,6,.8)',
            opacity: lock,
            transform: `translate3d(0, ${(1 - lock) * 28}px, 0) scale(${0.92 + lock * .08})`,
          }}
        >
          <div className="mono" style={{color: palette.greenDark, fontSize: 11, fontWeight: 730, letterSpacing: '.15em'}}>IMMUTABLE SNAPSHOT</div>
          <div style={{marginTop: 10, fontSize: 26, fontWeight: 650}}>Knowable before deadline</div>
          <div className="mono" style={{marginTop: 15, color: '#647067', fontSize: 11}}>{data.decision.fingerprint.slice(0, 16)}…</div>
        </div>
      </div>
      <Caption>Fresh data is useful. Temporally correct data is defensible.</Caption>
    </SceneShell>
  );
};

const Processor = ({label, sublabel, active, gpu = false}: {label: string; sublabel: string; active: number; gpu?: boolean}) => (
  <div
    style={{
      position: 'relative',
      width: 390,
      height: 252,
      padding: 10,
      borderRadius: 38,
      background: gpu ? 'rgba(130,173,138,.16)' : 'rgba(239,244,237,.07)',
      boxShadow: 'inset 0 1px 0 rgba(255,255,255,.1)',
      transform: `translate3d(0, ${(1 - active) * 35}px, 0) scale(${.93 + active * .07})`,
      opacity: active,
    }}
  >
    <div style={{height: '100%', padding: '31px', borderRadius: 29, background: gpu ? '#dce9dc' : '#1b2720', color: gpu ? palette.ink : palette.paper, boxShadow: 'inset 0 1px 0 rgba(255,255,255,.15)'}}>
      <div className="mono" style={{fontSize: 11, fontWeight: 720, letterSpacing: '.15em', color: gpu ? palette.greenDark : palette.green}}>{gpu ? 'CUDA / BLACKWELL' : 'MODEL FAMILY'}</div>
      <div style={{marginTop: 18, fontSize: 36, fontWeight: 640, letterSpacing: '-.04em'}}>{label}</div>
      <div style={{marginTop: 8, color: gpu ? '#5d6c62' : palette.muted, fontSize: 17, lineHeight: 1.4}}>{sublabel}</div>
      <div style={{display: 'flex', gap: 7, marginTop: 31}}>
        {Array.from({length: 10}, (_, i) => (
          <div key={i} style={{width: 21, height: 21, borderRadius: 6, background: i / 10 < active ? (gpu ? palette.greenDark : palette.green) : 'rgba(130,173,138,.12)', opacity: .45 + ((i * 7) % 9) / 16}} />
        ))}
      </div>
    </div>
  </div>
);

const ForecastScene = () => {
  const frame = useCurrentFrame();
  const direct = spring({frame: frame - 55, fps: 30, config: {damping: 19, stiffness: 100}});
  const component = spring({frame: frame - 78, fps: 30, config: {damping: 19, stiffness: 100}});
  const gpu = spring({frame: frame - 105, fps: 30, config: {damping: 17, stiffness: 108}});
  const connector = interpolate(frame, [135, 200], [0, 1], clamp);
  return (
    <SceneShell duration={SCENES.forecast.duration}>
      <SceneIndex index={3} />
      <div style={{position: 'absolute', left: 112, top: 168}}>
        <SceneTitle
          eyebrow="Forecast forge"
          title={<>Not one model.<br />Two ways to be wrong.</>}
          body={<>A direct player model and a correlated football simulator create independent evidence. The RTX 5090 accelerates trained-tree inference; it does not get a vote.</>}
          width={720}
        />
        <div style={{display: 'flex', gap: 42, marginTop: 50}}>
          <Metric label="MODELED PLAYERS" value={<CountUp to={data.search.players} start={30} />} delay={34} />
          <Metric label="PLAYER × EVENT ROWS" value={<CountUp to={data.search.playerEvents} start={42} />} delay={46} accent />
        </div>
      </div>
      <div style={{position: 'absolute', right: 92, top: 242, width: 900}}>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20}}>
          <Processor label="Direct xP" sublabel="appearance · minutes · returns" active={direct} />
          <Processor label="Component worlds" sublabel="goals · assists · clean sheets · bonus" active={component} />
        </div>
        <div style={{height: 70, marginInline: 210, borderLeft: `1px solid ${palette.line}`, borderRight: `1px solid ${palette.line}`, transform: `scaleY(${connector})`, transformOrigin: 'top'}} />
        <div style={{marginLeft: 210}}>
          <Processor label="RTX 5090" sublabel="CUDA-native XGBoost inference" active={gpu} gpu />
        </div>
      </div>
      <Caption>Hardware buys more experiments and deeper holdouts—not automatic accuracy.</Caption>
    </SceneShell>
  );
};

const SearchScene = () => {
  const frame = useCurrentFrame();
  const fieldProgress = interpolate(frame, [30, 180], [0, 1], clamp);
  const gateProgress = interpolate(frame, [185, 470], [0, 1], clamp);
  const gates = [
    {label: 'LEGAL UNIVERSE', value: data.search.universe, at: 0},
    {label: 'MULTI-OBJECTIVE', value: data.search.discovery, at: .27},
    {label: 'RESIDUAL SCREEN', value: data.search.residual, at: .57},
    {label: 'DEEP FINALISTS', value: data.search.finalists, at: .84},
  ];
  return (
    <SceneShell duration={SCENES.search.duration} style={{background: '#edf0e9', color: palette.ink}}>
      <div style={{position: 'absolute', inset: 0, opacity: .55, backgroundImage: 'linear-gradient(rgba(23,33,27,.055) 1px, transparent 1px), linear-gradient(90deg, rgba(23,33,27,.055) 1px, transparent 1px)', backgroundSize: '80px 80px'}} />
      <div style={{position: 'absolute', left: 100, top: 120, width: 1720}}>
        <div style={{display: 'flex', alignItems: 'end', justifyContent: 'space-between', gap: 50, ...appear(frame, 0)}}>
          <div>
            <Eyebrow>The candidate avalanche</Eyebrow>
            <h2 style={{margin: '23px 0 0', fontSize: 82, fontWeight: 580, letterSpacing: '-.062em', lineHeight: .95}}>Search wide. Spend compute late.</h2>
          </div>
          <div className="mono" style={{paddingBottom: 8, color: '#667168', fontSize: 16, textAlign: 'right', lineHeight: 1.7}}>
            {formatInt(data.search.seeds)} seed squads<br />{formatInt(data.search.oneSwap)} legal one-swaps<br />{formatInt(data.search.evolution)} evolutionary squads
          </div>
        </div>
        <div style={{position: 'relative', height: 565, marginTop: 54, overflow: 'hidden', borderRadius: 42, background: '#17211b', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.1), 0 32px 90px -60px rgba(23,33,27,.8)'}}>
          <div style={{position: 'absolute', inset: 0, background: 'radial-gradient(circle at 18% 52%, rgba(130,173,138,.17), transparent 35%)'}} />
          {candidateDots.map((dot, index) => {
            const progressOffset = ((index * 17) % 31) / 100;
            const p = Math.max(0, Math.min(1, gateProgress - progressOffset));
            const startX = 45 + dot.x * 680;
            const startY = 45 + dot.y * 470;
            const endX = 1590 + (dot.survivor ? (index % 5) * 15 : -120 + dot.x * 260);
            const endY = 170 + (index % 9) * 28;
            const fade = dot.survivor ? 1 : interpolate(p, [.62, .9], [1, 0], clamp);
            return (
              <div
                key={index}
                style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  width: 7 * dot.scale,
                  height: 7 * dot.scale,
                  borderRadius: 99,
                  background: dot.survivor ? '#c9df63' : '#d9dfd8',
                  opacity: dot.alpha * fieldProgress * fade,
                  transform: `translate3d(${startX + (endX - startX) * p}px, ${startY + (endY - startY) * p}px, 0)`,
                }}
              />
            );
          })}
          <svg width="1720" height="565" style={{position: 'absolute', inset: 0, opacity: .8}}>
            <path d="M 790 48 C 980 48, 980 118, 1120 118 C 1260 118, 1260 194, 1395 194 C 1510 194, 1510 270, 1640 270" fill="none" stroke="rgba(130,173,138,.45)" strokeWidth="2" strokeDasharray="8 10" />
          </svg>
          <div style={{position: 'absolute', inset: '0 35px', display: 'grid', gridTemplateColumns: '1.45fr .8fr .62fr .5fr', alignItems: 'end', gap: 28, paddingBottom: 40}}>
            {gates.map((gate, index) => {
              const active = interpolate(gateProgress, [gate.at - .08, gate.at + .08], [0, 1], clamp);
              return (
                <div key={gate.label} style={{position: 'relative', paddingTop: 22, borderTop: `1px solid ${active > .5 ? palette.green : 'rgba(239,244,237,.16)'}`, opacity: .42 + active * .58}}>
                  <div className="mono" style={{color: active > .5 ? palette.green : palette.muted, fontSize: 11, fontWeight: 720, letterSpacing: '.13em'}}>{gate.label}</div>
                  <div className="mono" style={{marginTop: 8, color: palette.paper, fontSize: index === 0 ? 52 : 42, fontWeight: 580, letterSpacing: '-.06em'}}>
                    {formatInt(gate.value)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <Caption tone="light">Cheap proxies discover. Independent simulations decide.</Caption>
    </SceneShell>
  );
};

const WorldsScene = () => {
  const frame = useCurrentFrame();
  const scan = interpolate(frame, [30, 310], [-120, 1680], clamp);
  return (
    <SceneShell duration={SCENES.worlds.duration}>
      <SceneIndex index={5} />
      <div style={{position: 'absolute', left: 112, top: 168, width: 680}}>
        <SceneTitle
          eyebrow="Trial by 25,000 worlds"
          title={<>Football happens together.</>}
          body={<>A clean sheet, a captain return and an autosub are not independent spreadsheet cells. Every finalist is scored through shared match worlds and exact FPL rules.</>}
          width={680}
        />
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32, marginTop: 54}}>
          <Metric label="BASE HOLDOUT" value={<CountUp to={data.search.holdoutWorlds} start={25} />} delay={30} />
          <Metric label="HIGH-GOAL STRESS" value={<CountUp to={data.search.stressWorlds} start={40} />} delay={42} accent />
        </div>
      </div>
      <div style={{position: 'absolute', right: 94, top: 148, width: 930, height: 760, overflow: 'hidden', borderRadius: 42, background: 'rgba(239,244,237,.045)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)'}}>
        {worldRows.map((row, index) => {
          const p = interpolate(frame, [row.delay, row.delay + 48], [0, 1], clamp);
          return (
            <div key={index} style={{position: 'absolute', left: 54 + row.x, top: row.y, width: row.width, height: 3, borderRadius: 99, background: row.good ? palette.green : palette.amber, opacity: .18 + .46 * p, transform: `scaleX(${p})`, transformOrigin: 'left'}} />
          );
        })}
        <div style={{position: 'absolute', top: 0, bottom: 0, left: scan, width: 2, background: palette.green, boxShadow: '20px 0 80px 20px rgba(130,173,138,.11)'}} />
        <div className="mono" style={{position: 'absolute', left: 52, right: 52, bottom: 35, display: 'flex', justifyContent: 'space-between', color: palette.muted, fontSize: 11, letterSpacing: '.12em'}}>
          <span>DNP + AUTOSUB</span><span>CAPTAIN FALLBACK</span><span>BONUS</span><span>TAIL RISK</span>
        </div>
      </div>
      <Caption>The five-week specialist emerges: <strong style={{color: palette.green}}>{data.search.leaderCallSign}</strong> <span className="mono" style={{color: palette.muted}}>({data.search.leader})</span>.</Caption>
    </SceneShell>
  );
};

const HorizonScene = () => {
  const frame = useCurrentFrame();
  const draw = interpolate(frame, [45, 250], [0, 1], clamp);
  const weeks = Array.from({length: 8}, (_, index) => index + 1);
  return (
    <SceneShell duration={SCENES.horizon.duration} light>
      <div style={{position: 'absolute', inset: 0, opacity: .45, backgroundImage: 'linear-gradient(rgba(23,33,27,.045) 1px, transparent 1px)', backgroundSize: '100% 86px'}} />
      <div style={{position: 'absolute', left: 108, top: 142, right: 108}}>
        <SceneTitle
          eyebrow="The horizon objects"
          title={<>GW1 is not an island.</>}
          body={<>The eight-week audit generates new challengers and solves open-transfer and forced-roll policies. A different squad wins—and that disagreement is preserved.</>}
          width={900}
        />
        <div style={{display: 'grid', gridTemplateColumns: '1fr 390px', gap: 72, marginTop: 68}}>
          <div style={{position: 'relative', height: 330}}>
            <svg viewBox="0 0 1160 330" width="1160" height="330" style={{position: 'absolute', inset: 0}}>
              <path d="M 35 202 C 180 165, 250 228, 355 178 S 545 116, 665 158 S 850 230, 1125 90" fill="none" stroke="#345b41" strokeWidth="5" strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - draw} />
              <path d="M 35 238 C 170 242, 240 170, 360 212 S 560 258, 690 195 S 900 118, 1125 142" fill="none" stroke="#c79758" strokeWidth="3" strokeLinecap="round" pathLength="1" strokeDasharray="1" strokeDashoffset={1 - draw} opacity=".8" />
            </svg>
            <div style={{position: 'absolute', left: 0, right: 0, bottom: 7, display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)'}}>
              {weeks.map((week, index) => (
                <div key={week} style={{textAlign: 'center', opacity: interpolate(frame, [60 + index * 12, 82 + index * 12], [0, 1], clamp)}}>
                  <div style={{width: 9, height: 9, margin: '0 auto 13px', borderRadius: 99, background: index === 0 ? palette.amber : palette.greenDark}} />
                  <div className="mono" style={{color: '#677168', fontSize: 11, letterSpacing: '.12em'}}>GW{week}</div>
                </div>
              ))}
            </div>
          </div>
          <div style={{display: 'grid', gap: 18}}>
            <Metric label="HORIZON CHALLENGERS" value={<CountUp to={data.horizon.challengers} start={30} />} delay={34} />
            <Metric label="TRANSFER POLICIES" value={<CountUp to={data.horizon.policySolves} start={55} />} delay={48} />
            <Metric label="DEEP FINALISTS" value={<CountUp to={data.horizon.finalists} start={75} />} delay={62} accent />
          </div>
        </div>
      </div>
      <div style={{position: 'absolute', left: 110, bottom: 68, display: 'flex', alignItems: 'center', gap: 24, ...appear(frame, 180, 22)}}>
        <div style={{padding: '12px 16px', borderRadius: 12, background: palette.ink, color: palette.paper}}>
          <div style={{fontSize: 17, fontWeight: 680}}>{data.horizon.leaderCallSign}</div>
          <div className="mono" style={{marginTop: 3, color: palette.muted, fontSize: 10}}>{data.horizon.leader}</div>
        </div>
        <div style={{fontSize: 23, color: '#566159'}}>wins the horizon by <strong style={{color: palette.ink}}>+{data.horizon.centralDelta.toFixed(3)}</strong> decayed points.</div>
      </div>
    </SceneShell>
  );
};

const SynthesisScene = () => {
  const frame = useCurrentFrame();
  const settle = interpolate(frame, [120, 280], [0, 1], clamp);
  const ranking = data.synthesis.ranking;
  const min = Math.min(...ranking.map((row) => row.synthesisRegret));
  const max = Math.max(...ranking.map((row) => row.synthesisRegret));
  return (
    <SceneShell duration={SCENES.synthesis.duration}>
      <SceneIndex index={7} />
      <div style={{position: 'absolute', left: 108, top: 152, width: 720}}>
        <SceneTitle
          eyebrow="Cross-family synthesis"
          title={<>The specialists do not win.</>}
          body={<>The five-week leader and horizon leader are both excellent inside their favourite world. Production selects the candidate with the lowest regret across both.</>}
          width={690}
        />
        <div style={{marginTop: 58, padding: '28px 30px', borderRadius: 28, background: 'rgba(239,244,237,.055)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)', ...appear(frame, 45, 22)}}>
          <div className="mono" style={{display: 'flex', justifyContent: 'space-between', color: palette.muted, fontSize: 11, letterSpacing: '.12em'}}>
            <span>FIVE-WEEK WEIGHT</span><span>HORIZON WEIGHT</span>
          </div>
          <div style={{position: 'relative', height: 13, marginTop: 17, borderRadius: 99, background: 'rgba(239,244,237,.09)', overflow: 'hidden'}}>
            <div style={{position: 'absolute', left: '40.9%', width: '38.4%', height: '100%', background: palette.green}} />
            <div style={{position: 'absolute', left: '50%', top: -7, width: 2, height: 27, background: palette.paper}} />
          </div>
          <div style={{marginTop: 12, color: palette.muted, fontSize: 15}}>The published winner owns the broad middle: 40.9%–79.3% horizon weight.</div>
        </div>
      </div>
      <div style={{position: 'absolute', right: 100, top: 160, width: 900}}>
        <div className="mono" style={{display: 'grid', gridTemplateColumns: '55px 1fr 150px', gap: 16, padding: '0 20px 16px', color: palette.muted, fontSize: 11, letterSpacing: '.13em'}}>
          <span>RANK</span><span>CALL SIGN / REGRET BALANCE</span><span>SYNTHESIS</span>
        </div>
        <div style={{display: 'grid', gap: 12}}>
          {ranking.slice(0, 6).map((row, index) => {
            const width = 35 + ((max - row.synthesisRegret) / Math.max(.001, max - min)) * 65;
            const winner = row.candidateId === data.decision.candidateId;
            const initialOffset = index === 0 ? 100 : index === 1 ? -85 : index === 4 ? 55 : 0;
            return (
              <div
                key={row.candidateId}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '55px 1fr 150px',
                  alignItems: 'center',
                  gap: 16,
                  minHeight: 88,
                  padding: '12px 20px',
                  borderRadius: 20,
                  background: winner ? palette.greenPale : 'rgba(239,244,237,.045)',
                  color: winner ? palette.ink : palette.paper,
                  boxShadow: winner ? 'inset 0 1px 0 white' : 'inset 0 1px 0 rgba(255,255,255,.05)',
                  opacity: interpolate(frame, [30 + index * 10, 58 + index * 10], [0, 1], clamp),
                  transform: `translate3d(${initialOffset * (1 - settle)}px, 0, 0)`,
                }}
              >
                <div className="mono" style={{fontSize: 21, fontWeight: 650, color: winner ? palette.greenDark : palette.muted}}>{String(index + 1).padStart(2, '0')}</div>
                <div>
                  <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 20}}>
                    <div>
                      <div style={{fontSize: 20, fontWeight: 700, letterSpacing: '-.025em'}}>{row.callSign}</div>
                      <div className="mono" style={{marginTop: 3, color: winner ? '#65766b' : palette.muted, fontSize: 9, letterSpacing: '.06em'}}>{row.candidateId} · {row.callNote}</div>
                    </div>
                    <div className="mono" style={{fontSize: 12, color: winner ? '#52665a' : palette.muted}}>{row.formation}</div>
                  </div>
                  <div style={{height: 5, marginTop: 13, borderRadius: 99, background: winner ? 'rgba(52,91,65,.13)' : 'rgba(239,244,237,.08)', overflow: 'hidden'}}>
                    <div style={{width: `${width}%`, height: '100%', background: winner ? palette.greenDark : palette.green, transform: `scaleX(${settle})`, transformOrigin: 'left'}} />
                  </div>
                </div>
                <div className="mono" style={{textAlign: 'right', fontSize: 25, fontWeight: 640}}>{row.synthesisRegret.toFixed(3)}</div>
              </div>
            );
          })}
        </div>
      </div>
      <Caption>Robust does not mean timid. It means the answer survives reasonable disagreement.</Caption>
    </SceneShell>
  );
};

const Gate = ({
  title,
  metric,
  verdict,
  x,
  delay,
}: {
  title: string;
  metric: string;
  verdict: string;
  x: number;
  delay: number;
}) => {
  const frame = useCurrentFrame();
  const p = spring({frame: frame - delay, fps: 30, config: {damping: 16, stiffness: 105}});
  return (
    <div style={{position: 'absolute', left: x, top: 288, width: 420, height: 420, display: 'grid', placeItems: 'center', opacity: p, transform: `scale(${.7 + p * .3})`}}>
      <div style={{position: 'absolute', inset: 0, borderRadius: 999, border: `1px solid rgba(130,173,138,${.15 + p * .42})`, boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)'}} />
      <div style={{position: 'absolute', inset: 44, borderRadius: 999, border: `1px solid rgba(130,173,138,${.1 + p * .3})`}} />
      <div style={{width: 250, textAlign: 'center'}}>
        <div className="mono" style={{color: palette.green, fontSize: 12, fontWeight: 720, letterSpacing: '.15em'}}>{title}</div>
        <div style={{marginTop: 14, fontSize: 29, fontWeight: 650, lineHeight: 1.1}}>{metric}</div>
        <div className="mono" style={{display: 'inline-flex', marginTop: 23, padding: '9px 13px', borderRadius: 99, background: palette.greenPale, color: palette.greenDark, fontSize: 12, fontWeight: 760, letterSpacing: '.1em'}}>{verdict}</div>
      </div>
    </div>
  );
};

const GatesScene = () => {
  const frame = useCurrentFrame();
  const tokenX = interpolate(frame, [35, 120, 215, 310, 380], [70, 360, 820, 1280, 1700], clamp);
  const tokenY = 770 - Math.sin(interpolate(frame, [35, 380], [0, Math.PI * 3], clamp)) * 45;
  return (
    <SceneShell duration={SCENES.gates.duration}>
      <SceneIndex index={8} />
      <div style={{position: 'absolute', left: 108, top: 140, right: 108, display: 'flex', alignItems: 'end', justifyContent: 'space-between', gap: 40}}>
        <SceneTitle eyebrow="The publication gauntlet" title={<>A winner can still be vetoed.</>} body={<>Scoring rules, role uncertainty and live availability each get one last chance to stop publication.</>} width={1020} />
        <div className="mono" style={{paddingBottom: 9, color: palette.muted, fontSize: 13, textAlign: 'right', lineHeight: 1.7}}>NO SILENT OVERRIDES<br />NO PARTIAL PUBLICATION</div>
      </div>
      <Gate title="STRUCTURE" metric={`${data.gates.structure.candidates} squads × ${data.gates.structure.views} rule views`} verdict="PASS" x={240} delay={55} />
      <Gate title="ROLE" metric={`${data.gates.role.scenarios} counterfactual scenarios`} verdict="STABLE" x={750} delay={145} />
      <Gate title="AVAILABILITY" metric={`${data.gates.availability.clear} clear · ${data.gates.availability.verify} verify`} verdict="CURRENT" x={1260} delay={235} />
      <div
        style={{
          position: 'absolute',
          left: tokenX,
          top: tokenY,
          width: 86,
          height: 86,
          display: 'grid',
          placeItems: 'center',
          borderRadius: 99,
          background: '#c9df63',
          color: palette.ink,
          boxShadow: '0 25px 50px -24px rgba(0,0,0,.7), inset 0 1px 0 rgba(255,255,255,.8)',
          transform: `translate3d(-43px, -43px, 0) rotate(${frame * 1.2}deg)`,
          fontSize: 25,
          fontWeight: 780,
        }}
      >
        FA
      </div>
      <Caption>Only a coherent artifact set may replace the live workspace.</Caption>
    </SceneShell>
  );
};

const RevealScene = () => {
  const frame = useCurrentFrame();
  const pitchReveal = interpolate(frame, [45, 240], [0, 1], clamp);
  const benchReveal = interpolate(frame, [210, 360], [0, 1], clamp);
  return (
    <SceneShell duration={SCENES.reveal.duration} style={{background: '#edf0e9', color: palette.ink}}>
      <div style={{position: 'absolute', inset: 0, background: 'radial-gradient(circle at 76% 20%, rgba(95,143,109,.19), transparent 38%)'}} />
      <div style={{position: 'absolute', left: 92, top: 120, width: 610}}>
        <Eyebrow>The surviving squad</Eyebrow>
        <h2 style={{margin: '27px 0 22px', fontSize: 88, fontWeight: 580, lineHeight: .92, letterSpacing: '-.068em', ...appear(frame, 5)}}>
          Built to score.<br />Built to adapt.
        </h2>
        <p style={{maxWidth: 560, margin: 0, color: '#657068', fontSize: 25, lineHeight: 1.43, ...appear(frame, 24)}}>
          {data.decision.callSign} is a {data.decision.formation}, spends £{data.decision.budget.toFixed(1)}m and captains {data.decision.captain}. Its bench is planned depth, not forgotten budget.
        </p>
        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 30, marginTop: 48}}>
          <Metric label="CALL SIGN" value={<span style={{fontSize: 30}}>{data.decision.callSign}</span>} note={data.decision.candidateId} delay={34} accent />
          <Metric label="GW1 BENCH" value={`£${data.decision.benchSpend.toFixed(1)}m`} delay={45} />
        </div>
        <div style={{marginTop: 42, ...appear(frame, 250, 24)}}>
          <div className="mono" style={{color: '#667168', fontSize: 11, fontWeight: 720, letterSpacing: '.15em'}}>ORDERED BENCH</div>
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(2, 178px)', gap: 17, marginTop: 18}}>
            {data.decision.bench.map((player, index) => (
              <div key={player.element} style={{opacity: interpolate(benchReveal, [index * .16, index * .16 + .3], [0, 1], clamp), transform: `translate3d(0, ${(1 - benchReveal) * 25}px, 0)`}}>
                <Shirt player={player} small />
              </div>
            ))}
          </div>
        </div>
      </div>
      <div style={{position: 'absolute', right: -36, top: 90, transform: 'scale(.99) rotate(.7deg)'}}>
        <TeamPitch data={data} reveal={pitchReveal} />
      </div>
    </SceneShell>
  );
};

const OutroScene = () => {
  const frame = useCurrentFrame();
  const p = spring({frame: frame - 8, fps: 30, config: {damping: 18, stiffness: 90}});
  return (
    <SceneShell duration={SCENES.outro.duration}>
      <div style={{position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center', opacity: p, transform: `scale(${.94 + p * .06})`}}>
        <div>
          <Eyebrow>The receipt remains</Eyebrow>
          <h2 style={{margin: '28px 0 22px', fontSize: 92, fontWeight: 570, letterSpacing: '-.068em'}}>Every claim can be traced.</h2>
          <p style={{margin: 0, color: palette.muted, fontSize: 24}}>Read the technical whitepaper. Inspect the checksums. Rerun before the deadline.</p>
          <div className="mono" style={{marginTop: 35, color: palette.green, fontSize: 14, letterSpacing: '.1em'}}>{data.decision.fingerprint}</div>
        </div>
      </div>
    </SceneShell>
  );
};

const EpisodeBackground = () => {
  const frame = useCurrentFrame();
  return (
    <>
      <div className="episode-grid" style={{transform: `translate3d(0, ${(frame % 240) * .08}px, 0)`}} />
      <div
        style={{
          position: 'absolute',
          width: 760,
          height: 760,
          right: -260 + Math.sin(frame / 120) * 24,
          top: -330 + Math.cos(frame / 150) * 22,
          borderRadius: 999,
          background: 'radial-gradient(circle, rgba(130,173,138,.12), transparent 65%)',
          transform: `scale(${1 + Math.sin(frame / 90) * .04})`,
        }}
      />
    </>
  );
};

const sequence = (
  key: keyof typeof SCENES,
  name: string,
  child: ReactNode,
) => {
  const scene = SCENES[key];
  return (
    <Sequence key={key} from={scene.from} durationInFrames={scene.duration} name={name} premountFor={30}>
      {child}
    </Sequence>
  );
};

export const FplDecisionEpisode = () => (
  <AbsoluteFill className="episode-canvas">
    <EpisodeBackground />
    {sequence('intro', '01 — The problem', <IntroScene />)}
    {sequence('evidence', '02 — Evidence', <EvidenceScene />)}
    {sequence('forecast', '03 — Forecast forge', <ForecastScene />)}
    {sequence('search', '04 — Search funnel', <SearchScene />)}
    {sequence('worlds', '05 — Simulation worlds', <WorldsScene />)}
    {sequence('horizon', '06 — Horizon audit', <HorizonScene />)}
    {sequence('synthesis', '07 — Synthesis', <SynthesisScene />)}
    {sequence('gates', '08 — Publication gauntlet', <GatesScene />)}
    {sequence('reveal', '09 — Winning squad', <RevealScene />)}
    {sequence('outro', '10 — Receipt', <OutroScene />)}
    <ProgressChrome chapters={CHAPTERS} chapterFrames={CHAPTER_FRAMES} lightChapters={[3, 5, 8]} />
    <Audio src={staticFile('audio/fplagent-score.wav')} volume={0.82} />
  </AbsoluteFill>
);
