import type {CSSProperties, ReactNode} from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import type {EpisodeData, Player} from './types';

export const palette = {
  night: '#111914',
  ink: '#17211b',
  paper: '#f3f4ed',
  muted: '#a9b2aa',
  faint: 'rgba(239,244,237,.1)',
  line: 'rgba(239,244,237,.16)',
  green: '#82ad8a',
  greenDark: '#345b41',
  greenPale: '#dce9dc',
  amber: '#c79758',
  red: '#b96659',
} as const;

export const clamp = {
  extrapolateLeft: 'clamp' as const,
  extrapolateRight: 'clamp' as const,
};

export const formatInt = (value: number) =>
  new Intl.NumberFormat('en-GB', {maximumFractionDigits: 0}).format(value);

export const formatSeconds = (seconds: number) => {
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}:${String(remainder).padStart(2, '0')}`;
};

export const appear = (frame: number, delay = 0, distance = 42) => {
  const progress = spring({
    frame: frame - delay,
    fps: 30,
    config: {damping: 22, mass: 0.8, stiffness: 110},
  });
  return {
    opacity: progress,
    transform: `translate3d(0, ${distance * (1 - progress)}px, 0)`,
  } satisfies CSSProperties;
};

export const sceneEnvelope = (frame: number, duration: number) => ({
  opacity: interpolate(frame, [0, 6, duration - 6, duration], [0, 1, 1, 0], clamp),
  transform: `scale(${interpolate(frame, [0, duration], [1.012, 1], clamp)})`,
});

export const BrandMark = ({dark = false}: {dark?: boolean}) => (
  <div
    style={{
      width: 62,
      height: 62,
      display: 'grid',
      placeItems: 'center',
      borderRadius: '20px 20px 20px 8px',
      background: dark ? palette.night : palette.paper,
      color: dark ? palette.paper : palette.ink,
      boxShadow: dark
        ? 'inset 0 1px 0 rgba(255,255,255,.14)'
        : 'inset 0 1px 0 rgba(255,255,255,.9)',
      fontSize: 16,
      fontWeight: 790,
      letterSpacing: '-.07em',
    }}
  >
    FA
  </div>
);

export const Eyebrow = ({children, tone = 'green'}: {children: ReactNode; tone?: 'green' | 'amber'}) => (
  <div
    className="mono"
    style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 10,
      color: tone === 'green' ? palette.green : palette.amber,
      fontSize: 15,
      fontWeight: 720,
      letterSpacing: '.18em',
      textTransform: 'uppercase',
    }}
  >
    <span
      style={{
        width: 8,
        height: 8,
        borderRadius: 99,
        background: 'currentColor',
      }}
    />
    {children}
  </div>
);

export const SceneTitle = ({
  eyebrow,
  title,
  body,
  delay = 0,
  width = 980,
}: {
  eyebrow: string;
  title: ReactNode;
  body: ReactNode;
  delay?: number;
  width?: number;
}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{width, ...appear(frame, delay)}}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2
        style={{
          margin: '28px 0 20px',
          fontSize: 86,
          fontWeight: 570,
          lineHeight: 0.96,
          letterSpacing: '-.064em',
        }}
      >
        {title}
      </h2>
      <p
        style={{
          maxWidth: 860,
          margin: 0,
          color: palette.muted,
          fontSize: 27,
          lineHeight: 1.42,
          letterSpacing: '-.018em',
        }}
      >
        {body}
      </p>
    </div>
  );
};

export const Metric = ({
  label,
  value,
  note,
  delay = 0,
  accent = false,
}: {
  label: string;
  value: ReactNode;
  note?: string;
  delay?: number;
  accent?: boolean;
}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        minWidth: 220,
        padding: '23px 2px 21px',
        borderTop: `1px solid ${accent ? 'rgba(130,173,138,.65)' : palette.line}`,
        ...appear(frame, delay, 24),
      }}
    >
      <div
        className="mono"
        style={{
          marginBottom: 10,
          color: accent ? palette.green : palette.muted,
          fontSize: 14,
          fontWeight: 690,
          letterSpacing: '.13em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </div>
      <div style={{fontSize: 46, fontWeight: 620, letterSpacing: '-.045em'}}>{value}</div>
      {note ? (
        <div style={{marginTop: 7, color: palette.muted, fontSize: 16}}>{note}</div>
      ) : null}
    </div>
  );
};

export const CountUp = ({
  to,
  from = 0,
  start = 0,
  duration = 54,
  decimals = 0,
  suffix = '',
}: {
  to: number;
  from?: number;
  start?: number;
  duration?: number;
  decimals?: number;
  suffix?: string;
}) => {
  const frame = useCurrentFrame();
  const value = interpolate(frame, [start, start + duration], [from, to], clamp);
  const formatted =
    decimals > 0
      ? value.toFixed(decimals)
      : new Intl.NumberFormat('en-GB', {maximumFractionDigits: 0}).format(value);
  return <>{formatted}{suffix}</>;
};

export const Caption = ({children, tone = 'dark'}: {children: ReactNode; tone?: 'dark' | 'light'}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: 'absolute',
        left: 138,
        bottom: 74,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        maxWidth: 1260,
        color: tone === 'light' ? palette.ink : '#dfe4dd',
        fontSize: 24,
        lineHeight: 1.35,
        ...appear(frame, 18, 18),
      }}
    >
      <span style={{width: 42, height: 2, background: tone === 'light' ? palette.greenDark : palette.green}} />
      {children}
    </div>
  );
};

export const SceneShell = ({
  children,
  duration,
  light = false,
  style,
}: {
  children: ReactNode;
  duration: number;
  light?: boolean;
  style?: CSSProperties;
}) => {
  const frame = useCurrentFrame();
  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        background: light ? '#edf0e9' : palette.night,
        color: light ? palette.ink : palette.paper,
        ...sceneEnvelope(frame, duration),
        ...style,
      }}
    >
      {children}
    </div>
  );
};

const teamColor = (team: string) => {
  const colors: Record<string, string> = {
    'Man City': '#84b6c8',
    Everton: '#4269a8',
    'Man Utd': '#b94845',
    Bournemouth: '#9d4745',
    Liverpool: '#a94345',
    Brentford: '#b44a43',
    'Aston Villa': '#7b3f5c',
    Leeds: '#d5c89b',
    Sunderland: '#aa5148',
    "Nott'm Forest": '#9b4542',
    Brighton: '#5582b4',
  };
  return colors[team] ?? palette.greenDark;
};

export const Shirt = ({player, small = false}: {player: Player; small?: boolean}) => {
  const color = teamColor(player.team);
  return (
    <div style={{position: 'relative', width: small ? 170 : 204, textAlign: 'center'}}>
      <div
        style={{
          position: 'relative',
          width: small ? 62 : 76,
          height: small ? 63 : 78,
          margin: '0 auto -2px',
          background: color,
          clipPath: 'polygon(23% 8%, 36% 0, 64% 0, 77% 8%, 100% 25%, 86% 45%, 75% 37%, 75% 100%, 25% 100%, 25% 37%, 14% 45%, 0 25%)',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,.28)',
        }}
      >
        <div
          className="mono"
          style={{
            position: 'absolute',
            inset: 0,
            display: 'grid',
            placeItems: 'center',
            paddingTop: 13,
            color: '#f6f6ef',
            fontSize: small ? 10 : 12,
            fontWeight: 780,
          }}
        >
          {player.position}
        </div>
      </div>
      <div
        style={{
          position: 'relative',
          minHeight: small ? 47 : 54,
          display: 'grid',
          placeItems: 'center',
          padding: small ? '6px 9px' : '8px 11px',
          borderRadius: small ? 10 : 12,
          background: '#f5f6ef',
          color: palette.ink,
          boxShadow: '0 12px 30px -20px rgba(4,18,9,.75), inset 0 1px 0 white',
          fontSize: small ? 15 : 18,
          fontWeight: 680,
          letterSpacing: '-.03em',
          lineHeight: 1.05,
        }}
      >
        {player.name}
      </div>
      {player.captain || player.viceCaptain ? (
        <div
          className="mono"
          style={{
            position: 'absolute',
            top: small ? 43 : 53,
            left: small ? 48 : 60,
            width: small ? 23 : 27,
            height: small ? 23 : 27,
            display: 'grid',
            placeItems: 'center',
            borderRadius: 99,
            background: player.captain ? '#c9df63' : palette.paper,
            color: palette.ink,
            fontSize: small ? 10 : 11,
            fontWeight: 800,
            boxShadow: '0 5px 12px rgba(10,20,12,.22)',
          }}
        >
          {player.captain ? 'C' : 'V'}
        </div>
      ) : null}
    </div>
  );
};

const positionRows: Record<Player['position'], {top: number; columns: number}> = {
  GK: {top: 48, columns: 1},
  DEF: {top: 218, columns: 3},
  MID: {top: 430, columns: 4},
  FWD: {top: 652, columns: 3},
};

export const TeamPitch = ({data, reveal = 1}: {data: EpisodeData; reveal?: number}) => {
  const grouped = (['GK', 'DEF', 'MID', 'FWD'] as const).map((position) => ({
    position,
    players: data.decision.starters.filter((player) => player.position === position),
  }));
  return (
    <div
      style={{
        position: 'relative',
        width: 1130,
        height: 880,
        overflow: 'hidden',
        border: '1px solid rgba(255,255,255,.19)',
        borderRadius: 52,
        background:
          'repeating-linear-gradient(90deg, rgba(255,255,255,.025) 0 118px, rgba(0,0,0,.02) 118px 236px), #3f7652',
        boxShadow: 'inset 0 1px 0 rgba(255,255,255,.12), 0 40px 90px -50px rgba(7,20,11,.8)',
      }}
    >
      <svg width="1130" height="880" viewBox="0 0 1130 880" style={{position: 'absolute', inset: 0, opacity: 0.44}}>
        <rect x="35" y="28" width="1060" height="824" rx="4" fill="none" stroke="white" strokeWidth="2" />
        <line x1="35" x2="1095" y1="440" y2="440" stroke="white" strokeWidth="2" />
        <circle cx="565" cy="440" r="92" fill="none" stroke="white" strokeWidth="2" />
        <circle cx="565" cy="440" r="5" fill="white" />
        <rect x="358" y="28" width="414" height="132" fill="none" stroke="white" strokeWidth="2" />
        <rect x="358" y="720" width="414" height="132" fill="none" stroke="white" strokeWidth="2" />
      </svg>
      {grouped.flatMap(({position, players}, rowIndex) => {
        const spec = positionRows[position];
        return players.map((player, index) => {
          const available = 920;
          const x = 105 + (available / (players.length + 1)) * (index + 1) - 102;
          const delay = rowIndex * 0.12 + index * 0.055;
          const local = interpolate(reveal, [delay, Math.min(1, delay + 0.24)], [0, 1], clamp);
          return (
            <div
              key={player.element}
              style={{
                position: 'absolute',
                left: x,
                top: spec.top,
                opacity: local,
                transform: `translate3d(0, ${(1 - local) * 45}px, 0) scale(${0.88 + local * 0.12})`,
              }}
            >
              <Shirt player={player} />
            </div>
          );
        });
      })}
    </div>
  );
};

export const ProgressChrome = ({
  chapters,
  chapterFrames,
  lightChapters = [],
}: {
  chapters: string[];
  chapterFrames: number[];
  lightChapters?: number[];
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const progress = frame / (durationInFrames - 1);
  const chapterIndex = chapterFrames.reduce(
    (active, start, index) => (frame >= start ? index : active),
    0,
  );
  const onLight = lightChapters.includes(chapterIndex);
  const chromeColor = onLight ? 'rgba(23,33,27,.72)' : 'rgba(239,244,237,.72)';
  const mutedColor = onLight ? 'rgba(23,33,27,.46)' : 'rgba(239,244,237,.42)';
  const labelColor = onLight ? palette.ink : palette.paper;
  return (
    <>
      <div
        style={{
          position: 'absolute',
          top: 46,
          left: 58,
          right: 58,
          zIndex: 20,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          color: chromeColor,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 15}}>
          <BrandMark dark />
          <div>
            <div style={{fontSize: 16, fontWeight: 660}}>FPLAgent</div>
            <div className="mono" style={{marginTop: 3, color: mutedColor, fontSize: 11, letterSpacing: '.12em'}}>
              DECISION FILM / 2026–27
            </div>
          </div>
        </div>
        <div className="mono" style={{display: 'flex', alignItems: 'center', gap: 18, fontSize: 12, letterSpacing: '.1em'}}>
          <span>{String(chapterIndex + 1).padStart(2, '0')} / {String(chapters.length).padStart(2, '0')}</span>
          <span style={{color: labelColor}}>{chapters[chapterIndex]}</span>
        </div>
      </div>
      <div style={{position: 'absolute', left: 58, right: 58, bottom: 34, zIndex: 20, height: 2, background: onLight ? 'rgba(23,33,27,.12)' : 'rgba(239,244,237,.09)'}}>
        <div style={{height: '100%', width: `${progress * 100}%`, transformOrigin: 'left', background: palette.green}} />
      </div>
    </>
  );
};
