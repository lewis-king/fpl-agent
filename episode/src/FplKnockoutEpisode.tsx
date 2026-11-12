import {Audio} from '@remotion/media';
import type {CSSProperties, ReactNode} from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
} from 'remotion';
import episodeData from './data/episode-data.json';
import {
  clamp,
  formatInt,
  palette,
  ProgressChrome,
  SceneShell,
  TeamPitch,
} from './components';
import {SquadBattle} from './SquadBattle';
import type {EpisodeData} from './types';

const data = episodeData as EpisodeData;
type Contestant = EpisodeData['tournament']['contestants'][number];

export const FPL_AGENT_KNOCKOUT_FRAMES = 4200;

const SCENES = {
  draw: {from: 0, duration: 240},
  qualifiers: {from: 210, duration: 720},
  knockout: {from: 900, duration: 750},
  worlds: {from: 1620, duration: 570},
  horizon: {from: 2160, duration: 600},
  finals: {from: 2730, duration: 750},
  gauntlet: {from: 3450, duration: 360},
  champion: {from: 3780, duration: 420},
} as const;

const CHAPTERS = [
  'THE DRAW',
  'QUALIFYING',
  'THE CUT TO 64',
  '25,000 WORLDS',
  'HORIZON INVASION',
  'THE FINALS',
  'LAST VETOES',
  'CHAMPION',
];

const CHAPTER_FRAMES = Object.values(SCENES).map((scene) => scene.from);
const ease = Easing.bezier(0.16, 1, 0.3, 1);

const sampled = <T,>(rows: T[], count: number, offset = 0) =>
  Array.from({length: Math.min(count, rows.length)}, (_, index) =>
    rows[(index * 37 + offset * 53) % rows.length],
  );

const contestants = data.tournament.contestants;
const robustFinalists = contestants.filter((row) => row.robustFinalist);
const horizonFinalists = contestants.filter((row) => row.horizonFinalist);
const nonFinalists = contestants.filter((row) => !row.robustFinalist);
const topEight = contestants
  .filter((row) => row.synthesisRank !== null && row.synthesisRank <= 8)
  .sort((left, right) => (left.synthesisRank ?? 99) - (right.synthesisRank ?? 99));

const byRank = new Map(topEight.map((row) => [row.synthesisRank, row]));

const contestantTone = (candidateId: string) => {
  const seed = [...candidateId].reduce(
    (hash, character) => ((hash * 33) ^ character.charCodeAt(0)) >>> 0,
    5381,
  );
  const tones = ['#82ad8a', '#c79758', '#7193a7', '#a96e61', '#9b8ab2', '#6f9077'];
  return tones[seed % tones.length];
};

const stageProgress = (frame: number, start: number, end: number) =>
  interpolate(frame, [start, end], [0, 1], {...clamp, easing: ease});

const Arena = ({
  children,
  stage,
  detail,
  duration,
  light = false,
}: {
  children: ReactNode;
  stage: string;
  detail: string;
  duration: number;
  light?: boolean;
}) => {
  const frame = useCurrentFrame();
  const drift = Math.sin(frame / 64);
  return (
    <SceneShell duration={duration} light={light} style={{background: light ? '#edf0e9' : palette.night}}>
      {!light ? (
        <>
          <div
            style={{
              position: 'absolute',
              left: 420 + drift * 150,
              top: -460,
              width: 940,
              height: 1040,
              borderRadius: '50%',
              opacity: 0.32,
              transform: `rotate(${frame * 0.025}deg)`,
              background: 'radial-gradient(ellipse at center, rgba(130,173,138,.19), rgba(130,173,138,.035) 42%, transparent 69%)',
            }}
          />
          <div
            style={{
              position: 'absolute',
              right: -270 + drift * 80,
              bottom: -570,
              width: 980,
              height: 980,
              borderRadius: '50%',
              border: '1px solid rgba(199,151,88,.13)',
              boxShadow: '0 0 90px rgba(199,151,88,.035)',
              transform: `scale(${1 + Math.sin(frame / 48) * 0.035})`,
            }}
          />
        </>
      ) : null}
      <div
      className="mono"
      style={{
        position: 'absolute',
        left: 58,
        top: 138,
        zIndex: 12,
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        color: light ? palette.greenDark : palette.green,
        fontSize: 13,
        fontWeight: 760,
        letterSpacing: '.16em',
        textTransform: 'uppercase',
      }}
    >
      <span style={{width: 8, height: 8, borderRadius: 99, background: 'currentColor'}} />
      {stage}
      <span style={{color: light ? 'rgba(23,33,27,.38)' : 'rgba(239,244,237,.34)'}}>／</span>
      <span style={{color: light ? 'rgba(23,33,27,.58)' : 'rgba(239,244,237,.48)'}}>{detail}</span>
    </div>
      {children}
    </SceneShell>
  );
};

const SquadCard = ({
  contestant,
  compact = false,
  eliminated = false,
  selected = false,
  progress = 1,
  style,
}: {
  contestant: Contestant;
  compact?: boolean;
  eliminated?: boolean;
  selected?: boolean;
  progress?: number;
  style?: CSSProperties;
}) => {
  const tone = contestantTone(contestant.candidateId);
  const visible = Math.max(0, Math.min(1, progress));
  return (
    <div
      style={{
        position: 'relative',
        width: compact ? 188 : 286,
        height: compact ? 76 : 122,
        overflow: 'hidden',
        borderRadius: compact ? 13 : 19,
        color: selected ? palette.ink : palette.paper,
        background: selected ? '#e8efe6' : '#1b2720',
        boxShadow: selected
          ? '0 18px 48px -28px rgba(0,0,0,.65), inset 0 1px 0 rgba(255,255,255,.86)'
          : 'inset 0 1px 0 rgba(255,255,255,.08), 0 18px 44px -34px rgba(0,0,0,.9)',
        opacity: visible * (eliminated ? 0.2 : 1),
        transform: `translate3d(0, ${(1 - visible) * 22 + (eliminated ? 18 : 0)}px, 0) scale(${0.94 + visible * 0.06 - (eliminated ? 0.04 : 0)}) rotate(${eliminated ? -2.5 : 0}deg)`,
        ...style,
      }}
    >
      <div style={{position: 'absolute', inset: '0 auto 0 0', width: compact ? 5 : 7, background: tone}} />
      <div style={{padding: compact ? '12px 12px 9px 16px' : '18px 18px 14px 22px'}}>
        <div
          style={{
            overflow: 'hidden',
            color: selected ? palette.ink : palette.paper,
            fontSize: compact ? 13 : 19,
            fontWeight: 720,
            letterSpacing: '-.035em',
            lineHeight: 1.05,
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {contestant.callSign}
        </div>
        <div
          className="mono"
          style={{
            display: 'flex',
            gap: compact ? 8 : 12,
            marginTop: compact ? 7 : 11,
            color: selected ? 'rgba(23,33,27,.58)' : palette.muted,
            fontSize: compact ? 8 : 10,
            letterSpacing: '.07em',
            textTransform: 'uppercase',
          }}
        >
          <span>{contestant.formation}</span>
          <span>{contestant.captain}</span>
          {!compact ? <span>£{contestant.benchSpend.toFixed(1)}m bench</span> : null}
        </div>
      </div>
      <div style={{position: 'absolute', left: compact ? 16 : 22, right: 12, bottom: compact ? 8 : 12, display: 'flex', gap: 3}}>
        {contestant.players.slice(0, compact ? 6 : 10).map((name, index) => (
          <span
            key={`${name}-${index}`}
            style={{
              height: 2,
              flex: 1,
              background: index % 3 === 0 ? tone : selected ? 'rgba(23,33,27,.18)' : 'rgba(239,244,237,.15)',
            }}
          />
        ))}
      </div>
      {eliminated ? (
        <div
          className="mono"
          style={{
            position: 'absolute',
            right: 10,
            top: 8,
            color: palette.red,
            fontSize: compact ? 8 : 10,
            fontWeight: 820,
            letterSpacing: '.14em',
          }}
        >
          OUT
        </div>
      ) : null}
      {!compact ? (
        <div className="mono" style={{position: 'absolute', right: 14, bottom: 9, color: selected ? 'rgba(23,33,27,.35)' : 'rgba(239,244,237,.26)', fontSize: 8}}>
          {contestant.candidateId}
        </div>
      ) : null}
    </div>
  );
};

const BigCount = ({value, label, align = 'left'}: {value: string; label: string; align?: 'left' | 'right'}) => (
  <div style={{textAlign: align}}>
    <div className="mono" style={{color: palette.green, fontSize: 12, fontWeight: 760, letterSpacing: '.16em', textTransform: 'uppercase'}}>{label}</div>
    <div style={{marginTop: 6, color: palette.paper, fontSize: 84, fontWeight: 620, lineHeight: .9, letterSpacing: '-.065em'}}>{value}</div>
  </div>
);

const DrawScene = () => {
  const frame = useCurrentFrame();
  const cards = sampled(contestants, 36, 2);
  const count = interpolate(frame, [40, 180], [0, data.search.universe], clamp);
  const camera = stageProgress(frame, 0, 220);
  return (
    <Arena stage="The draw" detail="all legal builds enter" duration={SCENES.draw.duration}>
      <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
        {cards.map((contestant, index) => {
          const column = index % 6;
          const row = Math.floor(index / 6);
          const delay = index * 2;
          const enter = spring({frame: frame - delay, fps: 30, config: {damping: 19, stiffness: 90, mass: .8}});
          const x = 1050 + column * 210 - camera * (280 + row * 22);
          const y = 130 + row * 142 + Math.sin((frame + index * 19) / 32) * 8;
          return (
            <SquadCard
              key={contestant.candidateId}
              contestant={contestant}
              compact
              progress={enter}
              style={{position: 'absolute', transform: `translate3d(${x}px, ${y}px, 0) rotate(${(column - 2.5) * .7}deg)`, opacity: .28 + enter * .58}}
            />
          );
        })}
      </div>
      <div style={{position: 'absolute', left: 88, top: 280, zIndex: 4, width: 860}}>
        <div style={{fontSize: 104, fontWeight: 610, lineHeight: .86, letterSpacing: '-.075em'}}>
          Every squad gets a name.
          <br />Only one keeps it.
        </div>
        <div style={{display: 'flex', alignItems: 'end', gap: 26, marginTop: 65}}>
          <div style={{fontSize: 126, fontWeight: 650, lineHeight: .8, letterSpacing: '-.075em'}}>{formatInt(count)}</div>
          <div className="mono" style={{paddingBottom: 4, color: palette.muted, fontSize: 13, letterSpacing: '.14em'}}>LEGAL SQUADS DRAFTED</div>
        </div>
      </div>
      <div className="mono" style={{position: 'absolute', left: 90, bottom: 78, color: palette.green, fontSize: 12, letterSpacing: '.15em'}}>
        THE FIELD IS CLOSED · THE TOURNAMENT BEGINS
      </div>
    </Arena>
  );
};

const QualifierScene = () => {
  const frame = useCurrentFrame();
  const field = sampled(contestants, 96, 5);
  const proxyCut = stageProgress(frame, 130, 260);
  const shortlistCut = stageProgress(frame, 330, 465);
  const finalistCut = stageProgress(frame, 520, 660);
  const count = frame < 230
    ? Math.round(interpolate(frame, [40, 220], [data.search.universe, data.search.discovery], clamp))
    : frame < 440
      ? Math.round(interpolate(frame, [260, 430], [data.search.discovery, data.search.residual], clamp))
      : Math.round(interpolate(frame, [470, 650], [data.search.residual, data.search.finalists], clamp));
  const round = frame < 250 ? 'PROXY QUALIFIER' : frame < 470 ? 'RESIDUAL SCREEN' : 'COMPONENT CUT';
  return (
    <Arena stage="Qualifying" detail={`${round} · ${formatInt(count)} alive`} duration={SCENES.qualifiers.duration}>
      <div style={{position: 'absolute', left: 58, right: 58, top: 190, bottom: 92, overflow: 'hidden'}}>
        <div
          style={{
            position: 'absolute',
            left: '50%',
            top: '50%',
            width: 1810,
            display: 'grid',
            gridTemplateColumns: 'repeat(12, 1fr)',
            gap: 8,
            transform: `translate3d(-50%, -50%, 0) scale(${interpolate(frame, [0, 680], [1.08, .91], clamp)})`,
          }}
        >
          {field.map((contestant, index) => {
            const proxyAlive = contestant.robustFinalist || index % 3 === 0;
            const shortlistAlive = contestant.robustFinalist || index % 11 === 0;
            const eliminated =
              (proxyCut > .65 && !proxyAlive) ||
              (shortlistCut > .65 && !shortlistAlive) ||
              (finalistCut > .65 && !contestant.robustFinalist);
            const kick = eliminated
              ? interpolate(
                  frame,
                  [
                    !proxyAlive ? 190 : !shortlistAlive ? 390 : 580,
                    !proxyAlive ? 280 : !shortlistAlive ? 480 : 675,
                  ],
                  [0, 1],
                  clamp,
                )
              : 0;
            return (
              <SquadCard
                key={`${contestant.candidateId}-${index}`}
                contestant={contestant}
                compact
                eliminated={eliminated}
                progress={stageProgress(frame, index % 40, 50 + (index % 40))}
                style={{
                  width: 142,
                  height: 62,
                  transform: `translate3d(${(index % 2 ? 1 : -1) * kick * 110}px, ${kick * 120}px, 0) scale(${1 - kick * .18})`,
                  opacity: eliminated ? Math.max(.06, 1 - kick * .93) : 1,
                }}
              />
            );
          })}
        </div>
        {[170, 370, 560].map((start, index) => {
          const gate = stageProgress(frame, start, start + 38);
          return (
            <div
              key={start}
              style={{
                position: 'absolute',
                inset: 0,
                zIndex: 8,
                pointerEvents: 'none',
                opacity: interpolate(gate, [0, .5, 1], [0, 1, 0], clamp),
                transform: `translate3d(${interpolate(gate, [0, 1], [-900, 900], clamp)}px, 0, 0)`,
                background: 'linear-gradient(90deg, transparent 0 45%, rgba(130,173,138,.23) 49%, #dce9dc 50%, rgba(130,173,138,.23) 51%, transparent 55%)',
              }}
            />
          );
        })}
      </div>
      <div style={{position: 'absolute', right: 74, top: 110, zIndex: 13, minWidth: 330, padding: '18px 22px', borderRadius: 18, background: '#e8efe6', color: palette.ink}}>
        <div className="mono" style={{fontSize: 10, fontWeight: 800, letterSpacing: '.15em'}}>{round}</div>
        <div style={{marginTop: 3, fontSize: 44, fontWeight: 690, letterSpacing: '-.05em'}}>{formatInt(count)} <span style={{color: 'rgba(23,33,27,.38)', fontSize: 18}}>remain</span></div>
      </div>
    </Arena>
  );
};

const MatchRow = ({winner, loser, progress, index}: {winner: Contestant; loser: Contestant; progress: number; index: number}) => {
  const settle = Math.max(0, Math.min(1, progress));
  return (
    <div style={{position: 'relative', display: 'grid', gridTemplateColumns: '1fr 40px 1fr 100px', alignItems: 'center', gap: 10, minHeight: 86}}>
      <SquadCard contestant={winner} compact selected={settle > .82} progress={1} style={{width: 238}} />
      <div className="mono" style={{color: palette.muted, fontSize: 9, textAlign: 'center'}}>VS</div>
      <SquadCard contestant={loser} compact eliminated={settle > .62} progress={1} style={{width: 238}} />
      <div style={{display: 'flex', alignItems: 'center', gap: 8}}>
        <div style={{height: 2, flex: 1, background: 'rgba(239,244,237,.12)'}}>
          <div style={{height: '100%', transformOrigin: 'left', transform: `scaleX(${settle})`, background: palette.green}} />
        </div>
        <div className="mono" style={{width: 28, color: settle > .82 ? palette.green : palette.muted, fontSize: 9}}>{String(index + 1).padStart(2, '0')}</div>
      </div>
    </div>
  );
};

const KnockoutScene = () => {
  const frame = useCurrentFrame();
  const diverse = data.tournament.captainDiversity;
  const byCaptain = (captain: string) => diverse.find((row) => row.captain === captain);
  const fallback = (index: number) => diverse[index % diverse.length];
  const pairs = [
    {left: byCaptain('Haaland') ?? fallback(0), right: byCaptain('Mbeumo') ?? fallback(1), label: 'PREMIUM CAPTAIN TEST · HAALAND vs MBEUMO'},
    {left: byCaptain('Bruno Fernandes') ?? fallback(2), right: byCaptain('Semenyo') ?? fallback(3), label: 'MIDFIELD CAPTAIN TEST · BRUNO vs SEMENYO'},
    {left: byCaptain('Lacroix') ?? fallback(4), right: byCaptain('Tarkowski') ?? fallback(5), label: 'DEFENSIVE ARCHETYPES · LACROIX vs TARKOWSKI'},
    {left: byCaptain('Igor Thiago') ?? fallback(6), right: byCaptain('White') ?? fallback(7), label: 'STRUCTURE TEST · FORWARD vs DEFENDER CAPTAIN'},
  ];
  const pageDuration = SCENES.knockout.duration / pairs.length;
  const page = Math.min(pairs.length - 1, Math.floor(frame / pageDuration));
  const pageFrame = frame - page * pageDuration;
  const battle = pairs[page];
  const result = stageProgress(pageFrame, 45, pageDuration - 25);
  return (
    <Arena stage="The cut to 64" detail={`deep audit ${page + 1} of ${pairs.length} · ${data.tournament.diversity.distinctCaptains} captains protected`} duration={SCENES.knockout.duration}>
      <div style={{position: 'absolute', left: 72, right: 72, top: 170, bottom: 56}} key={`${battle.left.candidateId}-${battle.right.candidateId}`}>
        <SquadBattle left={battle.left} right={battle.right} progress={result} label={battle.label} />
      </div>
      <div className="mono" style={{position: 'absolute', right: 80, top: 132, color: palette.muted, fontSize: 8, letterSpacing: '.12em'}}>
        {data.tournament.diversity.captainCounterfactuals} EXPLICIT COUNTERFACTUALS · DIVERSITY GUARD {data.tournament.diversity.guardPassed ? 'PASS' : 'FAIL'}
      </div>
    </Arena>
  );
};

const WorldsScene = () => {
  const frame = useCurrentFrame();
  const field = sampled(robustFinalists, 32, 3);
  const worlds = Math.round(interpolate(frame, [25, 390], [0, data.search.holdoutWorlds], clamp));
  const reveal = stageProgress(frame, 390, 515);
  const leader = contestants.find((row) => row.candidateId === data.search.leader) ?? robustFinalists[0];
  return (
    <Arena stage="The worlds" detail={`${formatInt(worlds)} correlated futures`} duration={SCENES.worlds.duration}>
      <div style={{position: 'absolute', left: 70, right: 70, top: 190, bottom: 70}}>
        <div style={{position: 'absolute', left: 0, top: 0, width: 420}}>
          <BigCount value={formatInt(worlds)} label="worlds played" />
          <div className="mono" style={{marginTop: 32, color: palette.muted, fontSize: 11, lineHeight: 2.1, letterSpacing: '.12em'}}>
            BASELINE WEATHER<br />AUTOSUB CHAOS<br />HIGH-GOAL STRESS<br />ROLLED GW2 TRANSFERS
          </div>
        </div>
        <div style={{position: 'absolute', left: 455, right: 0, top: 0, bottom: 0, overflow: 'hidden', borderRadius: 38, background: '#17231c', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)'}}>
          <div style={{position: 'absolute', inset: 34, display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12}}>
            {field.map((contestant, index) => {
              const noise = Math.sin(frame / 16 + index * 1.91) * 11 + Math.sin(frame / 7 + index) * 4;
              const orderLift = contestant.candidateId === leader.candidateId ? -42 * reveal : 18 * reveal;
              return (
                <SquadCard
                  key={contestant.candidateId}
                  contestant={contestant}
                  compact
                  selected={contestant.candidateId === leader.candidateId && reveal > .55}
                  progress={stageProgress(frame, index * 2, 50 + index * 2)}
                  style={{
                    width: 245,
                    transform: `translate3d(${noise * (1 - reveal)}px, ${orderLift}px, 0) scale(${contestant.candidateId === leader.candidateId ? 1 + reveal * .08 : 1 - reveal * .05})`,
                    opacity: contestant.candidateId === leader.candidateId ? 1 : 1 - reveal * .63,
                  }}
                />
              );
            })}
          </div>
          <div style={{position: 'absolute', left: 36, right: 36, bottom: 25, display: 'flex', gap: 8}}>
            {Array.from({length: 40}, (_, index) => (
              <span key={index} style={{height: 4, flex: 1, borderRadius: 99, background: index / 40 < worlds / data.search.holdoutWorlds ? (index % 7 === 0 ? palette.amber : palette.green) : 'rgba(239,244,237,.08)'}} />
            ))}
          </div>
        </div>
        <div style={{position: 'absolute', left: 30, bottom: 42, opacity: reveal, transform: `translate3d(0, ${(1 - reveal) * 34}px,0)`}}>
          <div className="mono" style={{color: palette.green, fontSize: 11, fontWeight: 800, letterSpacing: '.15em'}}>TOP SEED EMERGES</div>
          <div style={{marginTop: 8, fontSize: 42, fontWeight: 670, letterSpacing: '-.045em'}}>{leader.callSign}</div>
          <div className="mono" style={{marginTop: 6, color: palette.muted, fontSize: 9}}>{leader.candidateId}</div>
        </div>
      </div>
    </Arena>
  );
};

const HorizonScene = () => {
  const frame = useCurrentFrame();
  const incumbents = sampled(robustFinalists, 24, 4);
  const challengers = sampled(contestants.filter((row) => !row.robustFinalist || row.horizonFinalist), 24, 7);
  const clash = stageProgress(frame, 110, 330);
  const cut = stageProgress(frame, 335, 530);
  const survivors = sampled(horizonFinalists, 24, 2);
  return (
    <Arena stage="Horizon invasion" detail="224 enter · 48 survive" duration={SCENES.horizon.duration}>
      <div style={{position: 'absolute', left: 58, right: 58, top: 190, bottom: 62, overflow: 'hidden'}}>
        <div style={{position: 'absolute', left: 0, top: 5, width: 430}}>
          <BigCount value="64" label="five-week incumbents" />
        </div>
        <div style={{position: 'absolute', right: 0, top: 5, width: 430}}>
          <BigCount value="160" label="challengers + neighbours" align="right" />
        </div>
        <div style={{position: 'absolute', left: 0, right: 0, top: 154, height: 510}}>
          {incumbents.map((contestant, index) => {
            const x = (index % 6) * 205;
            const y = Math.floor(index / 6) * 98;
            const survives = contestant.horizonFinalist;
            return (
              <SquadCard
                key={`i-${contestant.candidateId}`}
                contestant={contestant}
                compact
                eliminated={cut > .6 && !survives}
                style={{position: 'absolute', left: x, top: y, width: 190, transform: `translate3d(${clash * (760 - x) * .34}px, ${cut * (survives ? 140 : 330)}px, 0) scale(${1 - clash * .16})`, opacity: cut > .6 && !survives ? .06 : 1}}
              />
            );
          })}
          {challengers.map((contestant, index) => {
            const x = 1230 + (index % 6) * 205;
            const y = Math.floor(index / 6) * 98;
            const survives = contestant.horizonFinalist;
            return (
              <SquadCard
                key={`c-${contestant.candidateId}-${index}`}
                contestant={contestant}
                compact
                selected={survives && cut > .65}
                eliminated={cut > .6 && !survives}
                style={{position: 'absolute', left: x, top: y, width: 190, transform: `translate3d(${-clash * (x - 760) * .34}px, ${cut * (survives ? 140 : 330)}px, 0) scale(${1 - clash * .16})`, opacity: cut > .6 && !survives ? .06 : 1}}
              />
            );
          })}
          <div style={{position: 'absolute', left: '50%', top: -30, bottom: 0, width: 2, transform: `translateX(-50%) scaleY(${clash})`, transformOrigin: 'top', background: palette.green}} />
        </div>
        <div style={{position: 'absolute', left: '50%', bottom: 18, display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 6, width: 990, transform: `translate3d(-50%, ${(1 - cut) * 95}px, 0)`, opacity: cut}}>
          {survivors.map((contestant) => (
            <div key={contestant.candidateId} title={contestant.callSign} style={{height: 24, borderRadius: 6, background: contestantTone(contestant.candidateId), boxShadow: 'inset 0 1px 0 rgba(255,255,255,.28)'}} />
          ))}
        </div>
        <div style={{position: 'absolute', left: '50%', bottom: 64, transform: 'translateX(-50%)', textAlign: 'center', opacity: cut}}>
          <div style={{fontSize: 62, fontWeight: 680, letterSpacing: '-.06em'}}>48</div>
          <div className="mono" style={{color: palette.green, fontSize: 10, letterSpacing: '.15em'}}>DEEP FINALISTS</div>
        </div>
      </div>
    </Arena>
  );
};

const Duel = ({
  left,
  right,
  progress,
  label,
  style,
}: {
  left: Contestant;
  right: Contestant;
  progress: number;
  label: string;
  style?: CSSProperties;
}) => {
  const frame = useCurrentFrame();
  const leftScore = left.synthesisRegret ?? 99;
  const rightScore = right.synthesisRegret ?? 99;
  const leftWins = leftScore <= rightScore;
  const decided = progress > .66;
  const pulse = Math.sin(frame / 5.5) * (decided ? 1 : 0);
  const scan = (frame * 8.5) % 760;
  return (
    <div style={{width: 680, padding: 15, overflow: 'hidden', borderRadius: 28, background: 'rgba(239,244,237,.045)', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.07)', ...style}}>
      <div style={{position: 'absolute', left: scan - 190, top: 0, bottom: 0, width: 160, opacity: .22, transform: 'skewX(-18deg)', background: 'linear-gradient(90deg, transparent, rgba(130,173,138,.18), transparent)'}} />
      <div className="mono" style={{margin: '1px 5px 12px', color: palette.muted, fontSize: 9, letterSpacing: '.14em'}}>{label}</div>
      <div style={{display: 'grid', gridTemplateColumns: '1fr 50px 1fr', alignItems: 'center', gap: 8}}>
        <div style={{transform: `translate3d(${decided ? (leftWins ? 4 + pulse * 2 : -10) : 0}px, 0, 0) scale(${decided && leftWins ? 1.018 + pulse * .003 : 1})`}}>
          <SquadCard contestant={left} selected={decided && leftWins} eliminated={decided && !leftWins} style={{width: 290}} />
          <div className="mono" style={{marginTop: 7, color: leftWins && decided ? palette.green : palette.muted, fontSize: 10}}>REGRET {leftScore.toFixed(3)}</div>
        </div>
        <div className="mono" style={{color: decided ? palette.green : palette.muted, fontSize: decided ? 15 : 10, fontWeight: 820, textAlign: 'center', transform: `scale(${1 + Math.abs(pulse) * .05})`}}>{decided ? '✓' : 'VS'}</div>
        <div style={{transform: `translate3d(${decided ? (!leftWins ? -4 - pulse * 2 : 10) : 0}px, 0, 0) scale(${decided && !leftWins ? 1.018 + pulse * .003 : 1})`}}>
          <SquadCard contestant={right} selected={decided && !leftWins} eliminated={decided && leftWins} style={{width: 290}} />
          <div className="mono" style={{marginTop: 7, color: !leftWins && decided ? palette.green : palette.muted, fontSize: 10}}>REGRET {rightScore.toFixed(3)}</div>
        </div>
      </div>
      <div style={{position: 'absolute', left: 15, right: 15, bottom: 5, height: 2, background: 'rgba(239,244,237,.07)'}}>
        <div style={{height: '100%', transformOrigin: 'left', transform: `scaleX(${Math.min(1, progress)})`, background: decided ? palette.green : palette.amber}} />
      </div>
    </div>
  );
};

const FinalsScene = () => {
  const frame = useCurrentFrame();
  const sweep = (frame * 13) % 2250 - 420;
  const bracketTrace = interpolate(frame % 92, [0, 78, 92], [0, 1, 0], clamp);
  const r1 = byRank.get(1)!;
  const r2 = byRank.get(2)!;
  const r3 = byRank.get(3)!;
  const r4 = byRank.get(4)!;
  const r5 = byRank.get(5)!;
  const r6 = byRank.get(6)!;
  const r7 = byRank.get(7)!;
  const r8 = byRank.get(8)!;
  const qf = [
    stageProgress(frame, 38, 98),
    stageProgress(frame, 86, 146),
    stageProgress(frame, 134, 194),
    stageProgress(frame, 182, 242),
  ];
  const semi = [stageProgress(frame, 260, 345), stageProgress(frame, 335, 420)];
  const final = stageProgress(frame, 475, 650);
  const qfOpacity = interpolate(frame, [0, 45, 225, 280], [0, 1, 1, 0], clamp);
  const semiOpacity = interpolate(frame, [235, 275, 440, 495], [0, 1, 1, 0], clamp);
  const finalOpacity = interpolate(frame, [455, 500], [0, 1], clamp);
  return (
    <Arena stage="The finals" detail="eight call signs · one champion" duration={SCENES.finals.duration}>
      <div style={{position: 'absolute', inset: '195px 70px 64px'}}>
        <div style={{position: 'absolute', left: sweep, top: -220, zIndex: 0, width: 330, height: 1160, opacity: .12, transform: 'skewX(-17deg)', background: 'linear-gradient(90deg, transparent, rgba(130,173,138,.32), transparent)'}} />
        <div style={{position: 'absolute', inset: 0, opacity: qfOpacity, transform: `scale(${.97 + qfOpacity * .03})`}}>
          <svg width="1780" height="820" viewBox="0 0 1780 820" style={{position: 'absolute', inset: 0, overflow: 'visible', opacity: .7}}>
            {[
              'M 560 102 H 740 Q 775 102 775 138 V 365 H 846',
              'M 1220 102 H 1040 Q 1005 102 1005 138 V 365 H 934',
              'M 560 718 H 740 Q 775 718 775 682 V 455 H 846',
              'M 1220 718 H 1040 Q 1005 718 1005 682 V 455 H 934',
            ].map((path) => (
              <path key={path} d={path} fill="none" stroke="rgba(130,173,138,.5)" strokeWidth="2" strokeDasharray="9 12" strokeDashoffset={-frame * 1.8} />
            ))}
          </svg>
          <Duel left={r1} right={r8} progress={qf[0]} label="QUARTERFINAL 01" style={{position: 'absolute', left: 0, top: 0, transform: 'scale(.82)', transformOrigin: 'top left'}} />
          <Duel left={r4} right={r5} progress={qf[1]} label="QUARTERFINAL 02" style={{position: 'absolute', right: 0, top: 0, transform: 'scale(.82)', transformOrigin: 'top right'}} />
          <Duel left={r2} right={r7} progress={qf[2]} label="QUARTERFINAL 03" style={{position: 'absolute', left: 0, bottom: 0, transform: 'scale(.82)', transformOrigin: 'bottom left'}} />
          <Duel left={r3} right={r6} progress={qf[3]} label="QUARTERFINAL 04" style={{position: 'absolute', right: 0, bottom: 0, transform: 'scale(.82)', transformOrigin: 'bottom right'}} />
          <div style={{position: 'absolute', left: '50%', top: '50%', width: 118, height: 118, display: 'grid', placeItems: 'center', transform: 'translate(-50%,-50%) rotate(45deg)', border: '1px solid rgba(130,173,138,.5)', background: palette.night}}>
            <span className="mono" style={{transform: `rotate(-45deg) scale(${1 + bracketTrace * .08})`, color: palette.green, fontSize: 10, letterSpacing: '.15em'}}>TOP 8</span>
          </div>
        </div>
        <div style={{position: 'absolute', inset: 0, opacity: semiOpacity}}>
          <Duel left={r1} right={r4} progress={semi[0]} label="SEMIFINAL 01" style={{position: 'absolute', left: 50, top: '50%', transform: 'translateY(-50%) scale(.9)', transformOrigin: 'left center'}} />
          <Duel left={r2} right={r3} progress={semi[1]} label="SEMIFINAL 02" style={{position: 'absolute', right: 50, top: '50%', transform: 'translateY(-50%) scale(.9)', transformOrigin: 'right center'}} />
          <div className="mono" style={{position: 'absolute', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', color: palette.green, fontSize: 12, letterSpacing: '.18em'}}>FINALISTS</div>
        </div>
        <div style={{position: 'absolute', inset: 0, opacity: finalOpacity}}>
          <div style={{position: 'absolute', left: '50%', top: 12, transform: 'translateX(-50%)', textAlign: 'center'}}>
            <div className="mono" style={{color: palette.green, fontSize: 12, letterSpacing: '.18em'}}>THE SYNTHESIS FINAL</div>
            <div style={{marginTop: 6, fontSize: 37, fontWeight: 630, letterSpacing: '-.04em'}}>Lowest regret across both audit families wins.</div>
          </div>
          <Duel left={r1} right={r2} progress={final} label="CHAMPIONSHIP MATCH" style={{position: 'absolute', left: '50%', top: '52%', width: 790, transform: `translate(-50%,-50%) scale(${1 + final * .11})`, transformOrigin: 'center'}} />
          {Array.from({length: 14}, (_, index) => (
            <span
              key={index}
              style={{
                position: 'absolute',
                left: `${8 + ((frame * (0.16 + (index % 4) * .035) + index * 17) % 84)}%`,
                top: `${32 + (index % 7) * 6}%`,
                width: 18 + (index % 3) * 13,
                height: 2,
                opacity: final * .35,
                background: index % 4 === 0 ? palette.amber : palette.green,
              }}
            />
          ))}
          <div className="mono" style={{position: 'absolute', left: '50%', bottom: 6, transform: 'translateX(-50%)', color: palette.muted, fontSize: 10, letterSpacing: '.12em', opacity: final}}>
            WINNING MARGIN · {((r2.synthesisRegret ?? 0) - (r1.synthesisRegret ?? 0)).toFixed(3)} REGRET
          </div>
        </div>
      </div>
    </Arena>
  );
};

const FullFinalsScene = () => {
  const frame = useCurrentFrame();
  const finalists = data.tournament.synthesisFinalists;
  const rank = (value: number) => finalists.find((row) => row.synthesisRank === value) ?? finalists[value - 1];
  const battles = [
    {left: rank(1), right: rank(4), label: 'SYNTHESIS SEMIFINAL 01 · FIVE-WEEK + EIGHT-WEEK REGRET'},
    {left: rank(2), right: rank(3), label: 'SYNTHESIS SEMIFINAL 02 · FIVE-WEEK + EIGHT-WEEK REGRET'},
    {left: rank(1), right: rank(2), label: 'CHAMPIONSHIP MATCH · LOWEST JOINT REGRET WINS'},
  ];
  const pageDuration = SCENES.finals.duration / battles.length;
  const page = Math.min(battles.length - 1, Math.floor(frame / pageDuration));
  const localFrame = frame - page * pageDuration;
  const battle = battles[page];
  const progress = stageProgress(localFrame, 68, pageDuration - 34);
  return (
    <Arena stage="The finals" detail={`full XV audit · match ${page + 1} of ${battles.length}`} duration={SCENES.finals.duration}>
      <div style={{position: 'absolute', left: 72, right: 72, top: 170, bottom: 56}} key={`${battle.left.candidateId}-${battle.right.candidateId}`}>
        <SquadBattle left={battle.left} right={battle.right} progress={progress} label={battle.label} metric="synthesis" />
      </div>
      <div className="mono" style={{position: 'absolute', left: 78, top: 132, color: palette.muted, fontSize: 8, letterSpacing: '.12em'}}>
        EVERY STARTER · EVERY BENCH SLOT · CAPTAINCY · AUTOSUB ORDER
      </div>
    </Arena>
  );
};

const Gate = ({x, title, detail, passed}: {x: number; title: string; detail: string; passed: number}) => (
  <div style={{position: 'absolute', left: x, top: 215, width: 280, height: 540, transform: 'translateX(-50%)'}}>
    <div style={{position: 'absolute', left: '50%', top: 0, bottom: 0, width: 2, transform: `translateX(-50%) scaleY(${.25 + passed * .75})`, background: passed > .72 ? palette.green : 'rgba(239,244,237,.14)'}} />
    {[0, 1, 2].map((ring) => (
      <div key={ring} style={{position: 'absolute', left: '50%', top: '50%', width: 180 + ring * 44, height: 180 + ring * 44, borderRadius: 999, border: `1px solid ${passed > .72 ? 'rgba(130,173,138,.65)' : 'rgba(239,244,237,.13)'}`, transform: `translate(-50%,-50%) rotate(${passed * (ring % 2 ? -40 : 40)}deg) scale(${.92 + passed * .08})`}} />
    ))}
    <div style={{position: 'absolute', left: '50%', bottom: 22, width: 280, transform: 'translateX(-50%)', textAlign: 'center'}}>
      <div style={{fontSize: 21, fontWeight: 680}}>{title}</div>
      <div className="mono" style={{marginTop: 6, color: palette.muted, fontSize: 9, letterSpacing: '.09em'}}>{detail}</div>
      <div className="mono" style={{marginTop: 11, color: passed > .72 ? palette.green : 'rgba(239,244,237,.28)', fontSize: 10, fontWeight: 820, letterSpacing: '.16em'}}>PASS</div>
    </div>
  </div>
);

const GauntletScene = () => {
  const frame = useCurrentFrame();
  const winner = byRank.get(1)!;
  const route = stageProgress(frame, 30, 310);
  const x = interpolate(route, [0, 1], [130, 1690], clamp);
  const gates = [
    {x: 520, title: 'Structure', detail: '21 squads × 5 rule views', progress: stageProgress(frame, 75, 135)},
    {x: 965, title: 'Role', detail: '4 counterfactual scenarios', progress: stageProgress(frame, 155, 215)},
    {x: 1410, title: 'Availability', detail: '14 clear · 1 verify', progress: stageProgress(frame, 235, 295)},
  ];
  return (
    <Arena stage="Last vetoes" detail="winning the model is not enough" duration={SCENES.gauntlet.duration}>
      <div style={{position: 'absolute', left: 58, right: 58, top: 180, bottom: 55}}>
        <div style={{position: 'absolute', left: 120, right: 120, top: '50%', height: 2, background: 'rgba(239,244,237,.1)'}}>
          <div style={{height: '100%', transformOrigin: 'left', transform: `scaleX(${route})`, background: palette.green}} />
        </div>
        {gates.map((gate) => <Gate key={gate.title} {...gate} passed={gate.progress} />)}
        <SquadCard contestant={winner} selected style={{position: 'absolute', left: x, top: '50%', zIndex: 8, width: 260, transform: `translate(-50%,-50%) scale(${1 + Math.sin(frame / 10) * .018})`}} />
        <div className="mono" style={{position: 'absolute', right: 70, top: 30, color: palette.green, fontSize: 11, fontWeight: 800, letterSpacing: '.16em', opacity: stageProgress(frame, 292, 330)}}>PUBLICATION CLEARED</div>
      </div>
    </Arena>
  );
};

const ChampionScene = () => {
  const frame = useCurrentFrame();
  const reveal = stageProgress(frame, 0, 85);
  const winner = byRank.get(1)!;
  const confetti = Array.from({length: 76}, (_, index) => ({
    x: (index * 181 + 47) % 1920,
    y: (index * 97 + 21) % 1080,
    size: 3 + (index % 5),
    tone: index % 5 === 0 ? palette.amber : index % 2 ? palette.green : palette.paper,
  }));
  return (
    <Arena stage="Champion" detail={`${winner.callSign} · ${winner.candidateId}`} duration={SCENES.champion.duration} light>
      <div style={{position: 'absolute', inset: 0, overflow: 'hidden'}}>
        {confetti.map((piece, index) => (
          <span key={index} style={{position: 'absolute', left: piece.x, top: piece.y, width: piece.size, height: 18 + (index % 4) * 6, background: piece.tone, opacity: reveal * .65, transform: `translate3d(${Math.sin((frame + index * 8) / 23) * 22}px, ${reveal * (frame * (1.2 + index % 3) - 160)}px,0) rotate(${frame * (index % 2 ? 1.2 : -.9)}deg)`}} />
        ))}
        <div style={{position: 'absolute', left: 82, top: 225, width: 670, zIndex: 3, opacity: reveal, transform: `translate3d(0, ${(1 - reveal) * 48}px,0)`}}>
          <div className="mono" style={{display: 'inline-flex', padding: '8px 12px', borderRadius: 99, color: '#edf0e9', background: palette.greenDark, fontSize: 10, fontWeight: 800, letterSpacing: '.17em'}}>FPLAGENT TOURNAMENT CHAMPION</div>
          <div style={{marginTop: 26, fontSize: 112, fontWeight: 650, lineHeight: .86, letterSpacing: '-.075em'}}>{winner.callSign}</div>
          <div style={{marginTop: 26, color: 'rgba(23,33,27,.62)', fontSize: 27, lineHeight: 1.35}}>{winner.callNote}</div>
          <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, max-content)', gap: 44, marginTop: 58}}>
            {[
              ['SHAPE', winner.formation],
              ['CAPTAIN', data.decision.captain],
              ['FINAL REGRET', (winner.synthesisRegret ?? 0).toFixed(3)],
            ].map(([label, value]) => (
              <div key={label}>
                <div className="mono" style={{color: 'rgba(23,33,27,.48)', fontSize: 9, letterSpacing: '.14em'}}>{label}</div>
                <div style={{marginTop: 7, fontSize: 22, fontWeight: 680}}>{value}</div>
              </div>
            ))}
          </div>
          <div className="mono" style={{marginTop: 62, color: 'rgba(23,33,27,.42)', fontSize: 10, letterSpacing: '.08em'}}>{winner.candidateId} · RECEIPT RETAINED</div>
          <div style={{marginTop: 18, paddingTop: 16, borderTop: '1px solid rgba(23,33,27,.12)'}}>
            <div className="mono" style={{color: 'rgba(23,33,27,.4)', fontSize: 9, letterSpacing: '.14em'}}>BENCH</div>
            <div style={{marginTop: 7, color: 'rgba(23,33,27,.66)', fontSize: 16, fontWeight: 610}}>{data.decision.bench.map((player) => player.name).join(' · ')}</div>
          </div>
        </div>
        <div style={{position: 'absolute', right: -52, top: 138, transform: `translate3d(${(1 - reveal) * 420}px,0,0) rotate(1.8deg) scale(.78)`, transformOrigin: 'top right'}}>
          <TeamPitch data={data} reveal={reveal} />
        </div>
        <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 16, background: palette.greenDark, transformOrigin: 'left', transform: `scaleX(${reveal})`}} />
      </div>
    </Arena>
  );
};

const TournamentEffects = () => {
  const frame = useCurrentFrame();
  const hits = [210, 900, 1620, 2160, 2730, 3450, 3780];
  const closest = Math.min(...hits.map((hit) => Math.abs(frame - hit)));
  const flash = interpolate(closest, [0, 2, 10], [0.72, 0.34, 0], clamp);
  const wipeHit = hits.reduce((closestHit, hit) => Math.abs(frame - hit) < Math.abs(frame - closestHit) ? hit : closestHit, hits[0]);
  const wipe = interpolate(frame - wipeHit, [-4, 0, 11], [0, 0.5, 1], clamp);
  return (
    <>
      <div
        style={{
          position: 'absolute',
          inset: 0,
          zIndex: 17,
          pointerEvents: 'none',
          opacity: flash,
          background: 'radial-gradient(circle at center, #f4f6ee 0%, rgba(220,233,220,.84) 33%, transparent 76%)',
          mixBlendMode: 'screen',
        }}
      />
      {closest < 15 ? (
        <div
          style={{
            position: 'absolute',
            top: 0,
            bottom: 0,
            left: `${interpolate(wipe, [0, 1], [-8, 108], clamp)}%`,
            zIndex: 18,
            width: 5,
            pointerEvents: 'none',
            opacity: interpolate(wipe, [0, 0.4, 1], [0, 1, 0], clamp),
            transform: 'skewX(-12deg)',
            background: palette.greenPale,
            boxShadow: '0 0 38px rgba(220,233,220,.55)',
          }}
        />
      ) : null}
    </>
  );
};

const sequence = (key: keyof typeof SCENES, child: ReactNode) => {
  const scene = SCENES[key];
  return (
    <Sequence key={key} from={scene.from} durationInFrames={scene.duration} name={CHAPTERS[Object.keys(SCENES).indexOf(key)]} premountFor={30}>
      {child}
    </Sequence>
  );
};

export const FplKnockoutEpisode = () => (
  <AbsoluteFill className="episode-canvas">
    <div className="episode-grid" />
    {sequence('draw', <DrawScene />)}
    {sequence('qualifiers', <QualifierScene />)}
    {sequence('knockout', <KnockoutScene />)}
    {sequence('worlds', <WorldsScene />)}
    {sequence('horizon', <HorizonScene />)}
    {sequence('finals', <FullFinalsScene />)}
    {sequence('gauntlet', <GauntletScene />)}
    {sequence('champion', <ChampionScene />)}
    <TournamentEffects />
    <ProgressChrome chapters={CHAPTERS} chapterFrames={CHAPTER_FRAMES} lightChapters={[7]} />
    <Audio src={staticFile('audio/fplagent-knockout-score.wav')} volume={0.9} />
  </AbsoluteFill>
);
