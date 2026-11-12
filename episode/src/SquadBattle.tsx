import type {CSSProperties} from 'react';
import {interpolate, spring, useCurrentFrame} from 'remotion';
import {clamp, palette} from './components';
import type {Player, TournamentContestant} from './types';

const colors: Record<string, string> = {
  Arsenal: '#bd4b45',
  'Aston Villa': '#81435f',
  Bournemouth: '#a74743',
  Brentford: '#bc4b43',
  Brighton: '#4e7eae',
  Burnley: '#823e57',
  Chelsea: '#4466a5',
  'Crystal Palace': '#526ca3',
  Everton: '#4269a8',
  Fulham: '#e8e7dc',
  Leeds: '#d8ca9b',
  Liverpool: '#aa4445',
  'Man City': '#81b4c6',
  'Man Utd': '#b94845',
  Newcastle: '#454d49',
  "Nott'm Forest": '#a34642',
  Sunderland: '#aa5148',
  Spurs: '#edece2',
  'West Ham': '#85445d',
  Wolves: '#c79758',
};

const playerColor = (player: Player) => colors[player.team] ?? '#52725e';

const PositionToken = ({
  player,
  unique,
  reveal,
  small = false,
}: {
  player: Player;
  unique: boolean;
  reveal: number;
  small?: boolean;
}) => (
  <div
    style={{
      position: 'relative',
      width: small ? 93 : 112,
      opacity: reveal,
      transform: `translate3d(0, ${(1 - reveal) * 20}px, 0) scale(${0.9 + reveal * 0.1})`,
      textAlign: 'center',
    }}
  >
    <div
      style={{
        position: 'relative',
        width: small ? 31 : 38,
        height: small ? 32 : 39,
        margin: '0 auto -1px',
        background: playerColor(player),
        clipPath: 'polygon(22% 8%,36% 0,64% 0,78% 8%,100% 26%,85% 47%,75% 38%,75% 100%,25% 100%,25% 38%,15% 47%,0 26%)',
        filter: unique ? 'drop-shadow(0 0 7px rgba(207,170,101,.5))' : undefined,
      }}
    >
      <span className="mono" style={{position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', paddingTop: 7, color: '#faf9f2', fontSize: small ? 6 : 7, fontWeight: 820}}>
        {player.position}
      </span>
    </div>
    <div
      style={{
        minHeight: small ? 25 : 31,
        display: 'grid',
        placeItems: 'center',
        overflow: 'hidden',
        padding: small ? '4px 4px' : '5px 5px',
        borderRadius: small ? 6 : 8,
        background: unique ? '#f4e8ce' : '#eef1e9',
        boxShadow: unique
          ? '0 8px 20px -12px rgba(0,0,0,.8), inset 0 0 0 1.5px rgba(199,151,88,.72)'
          : '0 8px 20px -14px rgba(0,0,0,.8), inset 0 1px 0 rgba(255,255,255,.9)',
        color: palette.ink,
        fontSize: small ? 7 : 9,
        fontWeight: 760,
        letterSpacing: '-.025em',
        lineHeight: 1,
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}
    >
      {player.name}
    </div>
    {player.captain || player.viceCaptain ? (
      <div
        className="mono"
        style={{
          position: 'absolute',
          left: small ? 22 : 26,
          top: small ? 25 : 31,
          width: small ? 16 : 18,
          height: small ? 16 : 18,
          display: 'grid',
          placeItems: 'center',
          borderRadius: 99,
          background: player.captain ? '#d5e66b' : '#f7f6ef',
          color: palette.ink,
          fontSize: small ? 6 : 7,
          fontWeight: 900,
          boxShadow: '0 3px 8px rgba(0,0,0,.24)',
        }}
      >
        {player.captain ? 'C' : 'V'}
      </div>
    ) : null}
  </div>
);

const rowTop: Record<Player['position'], number> = {GK: 15, DEF: 105, MID: 220, FWD: 340};

export const FullSquadCard = ({
  contestant,
  opponent,
  reveal = 1,
  winner = false,
  eliminated = false,
  metricLabel = 'ROBUST REGRET',
  metric,
  style,
}: {
  contestant: TournamentContestant;
  opponent?: TournamentContestant;
  reveal?: number;
  winner?: boolean;
  eliminated?: boolean;
  metricLabel?: string;
  metric?: number | null;
  style?: CSSProperties;
}) => {
  const opponentPlayers = new Set(opponent?.players ?? []);
  const local = Math.max(0, Math.min(1, reveal));
  const grouped = (['GK', 'DEF', 'MID', 'FWD'] as const).map((position) => ({
    position,
    players: contestant.starters.filter((player) => player.position === position),
  }));
  return (
    <div
      style={{
        position: 'relative',
        width: 710,
        height: 722,
        padding: 7,
        borderRadius: 34,
        background: winner ? 'rgba(130,173,138,.22)' : 'rgba(239,244,237,.055)',
        boxShadow: winner
          ? '0 36px 90px -55px rgba(130,173,138,.8), inset 0 0 0 1px rgba(177,214,183,.34)'
          : '0 30px 80px -58px rgba(0,0,0,.94), inset 0 0 0 1px rgba(255,255,255,.07)',
        opacity: local * (eliminated ? 0.34 : 1),
        transform: `translate3d(0, ${(1 - local) * 42 + (eliminated ? 16 : 0)}px, 0) scale(${0.94 + local * 0.06 - (eliminated ? .025 : 0)})`,
        ...style,
      }}
    >
      <div style={{position: 'relative', width: '100%', height: '100%', overflow: 'hidden', borderRadius: 27, background: '#16231b', boxShadow: 'inset 0 1px 0 rgba(255,255,255,.08)'}}>
        <div style={{height: 103, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 23px 15px'}}>
          <div style={{minWidth: 0}}>
            <div style={{overflow: 'hidden', color: palette.paper, fontSize: 25, fontWeight: 730, letterSpacing: '-.045em', lineHeight: 1.05, textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
              {contestant.callSign}
            </div>
            <div className="mono" style={{display: 'flex', gap: 12, marginTop: 9, color: palette.muted, fontSize: 8, letterSpacing: '.12em'}}>
              <span>{contestant.formation}</span>
              <span>CAP {contestant.captain}</span>
              <span>£{contestant.benchSpend.toFixed(1)}M BENCH</span>
            </div>
          </div>
          <div style={{flex: '0 0 auto', textAlign: 'right'}}>
            <div className="mono" style={{color: winner ? palette.green : palette.muted, fontSize: 7, letterSpacing: '.13em'}}>{metricLabel}</div>
            <div style={{marginTop: 3, color: winner ? '#b9d7bd' : palette.paper, fontSize: 26, fontWeight: 700, letterSpacing: '-.045em'}}>
              {metric === null || metric === undefined ? contestant.expectedPoints.toFixed(1) : metric.toFixed(3)}
            </div>
          </div>
        </div>

        <div
          style={{
            position: 'absolute',
            left: 20,
            right: 20,
            top: 103,
            height: 478,
            overflow: 'hidden',
            borderRadius: 22,
            background: 'repeating-linear-gradient(90deg,rgba(255,255,255,.018) 0 70px,rgba(0,0,0,.018) 70px 140px),#356d4c',
            boxShadow: 'inset 0 0 0 1px rgba(255,255,255,.16), inset 0 20px 60px rgba(5,22,12,.12)',
          }}
        >
          <svg width="670" height="478" viewBox="0 0 670 478" style={{position: 'absolute', inset: 0, opacity: .36}}>
            <rect x="15" y="14" width="640" height="450" rx="3" fill="none" stroke="white" />
            <line x1="15" x2="655" y1="239" y2="239" stroke="white" />
            <circle cx="335" cy="239" r="55" fill="none" stroke="white" />
            <rect x="224" y="14" width="222" height="74" fill="none" stroke="white" />
            <rect x="224" y="390" width="222" height="74" fill="none" stroke="white" />
          </svg>
          {grouped.flatMap(({position, players}, rowIndex) => players.map((player, index) => {
            const width = 640;
            const left = 15 + (width / (players.length + 1)) * (index + 1) - 56;
            const delay = rowIndex * .08 + index * .035;
            const tokenReveal = interpolate(local, [delay, Math.min(1, delay + .24)], [0, 1], clamp);
            return (
              <div key={player.element} style={{position: 'absolute', left, top: rowTop[position]}}>
                <PositionToken player={player} unique={!opponentPlayers.has(player.name)} reveal={tokenReveal} />
              </div>
            );
          }))}
        </div>

        <div style={{position: 'absolute', left: 20, right: 20, bottom: 18, height: 104, padding: '10px 12px', borderRadius: 18, background: '#edf0e9', color: palette.ink, boxShadow: 'inset 0 1px 0 rgba(255,255,255,.95)'}}>
          <div className="mono" style={{position: 'absolute', left: 15, top: 9, color: 'rgba(23,33,27,.46)', fontSize: 7, fontWeight: 780, letterSpacing: '.14em'}}>BENCH · AUTOSUB ORDER</div>
          <div style={{position: 'absolute', left: 102, right: 8, top: 7, display: 'flex', justifyContent: 'space-evenly'}}>
            {contestant.bench.map((player, index) => (
              <div key={player.element} style={{position: 'relative'}}>
                <span className="mono" style={{position: 'absolute', left: -4, top: 2, zIndex: 2, width: 14, height: 14, display: 'grid', placeItems: 'center', borderRadius: 99, background: palette.ink, color: palette.paper, fontSize: 6}}>{index + 1}</span>
                <PositionToken player={player} unique={!opponentPlayers.has(player.name)} reveal={local} small />
              </div>
            ))}
          </div>
        </div>
        {opponent ? (
          <div className="mono" style={{position: 'absolute', left: 25, bottom: 6, color: palette.amber, fontSize: 6, letterSpacing: '.11em'}}>
            GOLD = UNIQUE TO THIS XV
          </div>
        ) : null}
      </div>
    </div>
  );
};

export const SquadBattle = ({
  left,
  right,
  progress,
  label,
  metric = 'robust',
}: {
  left: TournamentContestant;
  right: TournamentContestant;
  progress: number;
  label: string;
  metric?: 'robust' | 'synthesis';
}) => {
  const frame = useCurrentFrame();
  const leftMetric = metric === 'synthesis' ? left.synthesisRegret : left.robustRegret;
  const rightMetric = metric === 'synthesis' ? right.synthesisRegret : right.robustRegret;
  const leftWins = (leftMetric ?? 999) <= (rightMetric ?? 999);
  const decided = progress > .66;
  const impact = spring({frame: frame - 52, fps: 30, config: {damping: 18, mass: .55, stiffness: 160}});
  const leftUnique = left.players.filter((name) => !right.players.includes(name));
  const rightUnique = right.players.filter((name) => !left.players.includes(name));
  return (
    <div style={{position: 'absolute', inset: 0}}>
      <div className="mono" style={{position: 'absolute', left: '50%', top: 4, transform: 'translateX(-50%)', color: palette.green, fontSize: 11, fontWeight: 820, letterSpacing: '.18em'}}>{label}</div>
      <FullSquadCard contestant={left} opponent={right} reveal={impact} winner={decided && leftWins} eliminated={decided && !leftWins} metricLabel={metric === 'synthesis' ? 'SYNTHESIS REGRET' : 'ROBUST REGRET'} metric={leftMetric} style={{position: 'absolute', left: 0, top: 42}} />
      <FullSquadCard contestant={right} opponent={left} reveal={impact} winner={decided && !leftWins} eliminated={decided && leftWins} metricLabel={metric === 'synthesis' ? 'SYNTHESIS REGRET' : 'ROBUST REGRET'} metric={rightMetric} style={{position: 'absolute', right: 0, top: 42}} />
      <div style={{position: 'absolute', left: '50%', top: 290, width: 160, height: 160, display: 'grid', placeItems: 'center', transform: `translate(-50%,-50%) scale(${.86 + impact * .14})`, borderRadius: 999, background: decided ? '#dce9dc' : '#1d2d23', color: decided ? palette.ink : palette.paper, boxShadow: '0 26px 68px -38px rgba(0,0,0,.9), inset 0 0 0 7px rgba(130,173,138,.12)'}}>
        <div style={{textAlign: 'center'}}>
          <div className="mono" style={{fontSize: 9, fontWeight: 850, letterSpacing: '.16em'}}>{decided ? 'ADVANCES' : 'AUDIT'}</div>
          <div style={{marginTop: 7, fontSize: decided ? 30 : 42, fontWeight: 760, letterSpacing: '-.05em'}}>{decided ? (leftWins ? 'LEFT' : 'RIGHT') : 'VS'}</div>
        </div>
      </div>
      <div style={{position: 'absolute', left: '50%', bottom: 0, width: 780, transform: 'translateX(-50%)', textAlign: 'center', opacity: interpolate(progress, [.25, .72], [0, 1], clamp)}}>
        <div className="mono" style={{color: palette.muted, fontSize: 8, letterSpacing: '.12em'}}>THE ACTUAL DIFFERENCE</div>
        <div style={{marginTop: 8, color: palette.paper, fontSize: 15, fontWeight: 620}}>
          <span style={{color: palette.amber}}>{left.callSign}:</span> {leftUnique.slice(0, 4).join(' · ')}
          <span style={{margin: '0 14px', color: 'rgba(239,244,237,.25)'}}>／</span>
          <span style={{color: palette.amber}}>{right.callSign}:</span> {rightUnique.slice(0, 4).join(' · ')}
        </div>
      </div>
    </div>
  );
};
